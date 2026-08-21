# TopoTestix Shrinker
#
# Pure Nix module for choice-based shrinking. Reduces individual choice indices
# toward 0 (lower index = simpler value) in fuzzer-generated configurations.
#
# The shrinker operates on three inputs:
#   - target: the original target spec (contains option lists)
#   - fuzzed: the fuzzer's resolved output (contains concrete values)
#   - choices_override: a map from path strings to indices (only overrides)
#
# When choices_override is empty, the shrinker is the identity function — it
# returns the fuzzed output unchanged. This means the normal (un-shrunk) pipeline
# works without any shrinking logic.
#
# Convention: lower index = simpler value. Target spec authors must order option
# lists from simplest to most complex. The shrinker always moves toward index 0.
#
# See docs/shrinking.md for full design documentation.

{ lib }:

let
  # normalizePath : string -> string
  #
  # Strip the leading dot from a path string.
  #
  normalizePath = path:
    if !(builtins.isString path) || path == "" || builtins.substring 0 1 path != "." then
      builtins.throw "shrinker: invalid path '${toString path}', expected a target-relative path like .virtualisation.memorySize"
    else
      builtins.substring 1 (builtins.stringLength path - 1) path;

  # tryKeyAtLen : attrset -> [string] -> int -> { value, remainder } or null
  #
  # Try to find a key formed by joining the first `len` parts with dots.
  # If found, returns { value = <found-value>; remainder = <remaining-parts> }.
  # Returns null if no matching key is found at this length.
  tryKeyAtLen = attrs: parts: len:
    let
      candidate = builtins.concatStringsSep "." (lib.take len parts);
      rest = lib.drop len parts;
    in
    if attrs ? ${candidate} then { value = attrs.${candidate}; remainder = rest; }
    else null;

  # findBestMatch : attrset -> [string] -> { value, remainder } or null
  #
  # Try to navigate into `attrs` starting from the given path parts.
  # Tries progressively longer keys to handle attribute names that
  # contain dots (e.g. "disk_free_limit.absolute" in RabbitMQ configItems).
  # Starts with len=1 (standard dot-split key) and increases until a match is found.
  findBestMatch = attrs: parts:
    let
      maxLen = builtins.length parts;
      matches = builtins.filter (match: match != null)
        (map (idx: tryKeyAtLen attrs parts idx) (lib.range 1 maxLen));
    in
    if builtins.length matches > 1 then
      builtins.throw "shrinker: ambiguous path matches both nested and dotted attribute names"
    else if matches == [] then null
    else builtins.head matches;

  # navigateDottedKeys handles attribute names that contain dots.
  # When a naive dot-split would land on a non-existent key, it tries
  # progressively longer candidates by combining parts with dots.
  # Returns { value, remainder } where remainder is the unconsumed suffix.
  navigateDottedKeys = attrs: parts:
    if parts == [] then
      { value = attrs; remainder = []; }
    else
      let r = findBestMatch attrs parts; in
      if r != null then r
      else builtins.throw "shrinker: path does not exist in target";

  # getValueByPath : attrset -> string -> value
  #
  # Navigate a nested attrset using a dot-separated path string.
  # Handles attribute names that contain embedded dots by trying progressively
  # longer key candidates at each level.
  #
  getValueByPath = attrs: path:
    let
      pathStr = normalizePath path;
      parts = lib.splitString "." pathStr;
      consumeAll = currentPos: remainingParts:
        if remainingParts == [] then currentPos
        else
          let r = navigateDottedKeys currentPos remainingParts; in
          if r.remainder != [] then consumeAll r.value r.remainder
          else r.value;
    in
    consumeAll attrs parts;

  # setValueByPath : attrset -> string -> value -> attrset
  #
  # Set a value at an existing nested path in an attrset.
  # Returns a new attrset with the value set at the specified path.
  #
  # Handles attribute names that contain dots by trying progressively longer
  # key candidates when a short split would miss the actual identifier.
  #
  setValueByPath = attrs: path: value:
    let
      pathStr = normalizePath path;
      parts = lib.splitString "." pathStr;
      match = findBestMatch attrs parts;
    in
    if builtins.length parts == 0 then
      attrs
    else if match == null then
      # A single leaf key can be added, but nested traversal must already exist.
      if builtins.length parts == 1 then
        attrs // { ${builtins.head parts} = value; }
      else
        builtins.throw "shrinker: cannot set path ${path} — no matching key found"
    else if match.remainder != [] then
      # Recurse into the matched sub-attrset.
      let
        keyName = builtins.concatStringsSep "." (lib.take (builtins.length parts - builtins.length match.remainder) parts);
        pathForRest = "." + builtins.concatStringsSep "." match.remainder;
      in
      attrs // { ${keyName} = setValueByPath match.value pathForRest value; }
    else
      # Final key — set the value.
      let
        keyName = builtins.concatStringsSep "." parts;
      in
      attrs // { ${keyName} = value; };

  # applyOverrides : target -> fuzzed -> choices_override -> attrset
  #
  # Walk the target spec and the fuzzed result simultaneously. For paths
  # present in choices_override, use the overridden index to pick from the
  # target's option list. For paths not in choices_override, use the fuzzed
  # value unchanged.
  #
  applyOverrides = target: fuzzed: choices_override:
    let
      paths = builtins.attrNames choices_override;
    in
    if paths == [] then fuzzed
    else
      lib.foldl' (acc: path:
        let
          idx = choices_override.${path};
          val = valueAtChecked target path idx;
        in
        setValueByPath acc path val
      ) fuzzed paths;

  # collectChoicePaths : string -> value -> [string]
  #
  # Walk a target spec and collect all paths where the value is a list.
  # Returns a list of dot-separated paths suitable for use as keys in
  # the choices map.
  #
  # Functions are called with { lib; } and their return value is recursed into,
  # matching the behavior of combinators.resolve.
  #
  collectChoicePaths = prefix: value:
    if builtins.isList value then
      if value == [] then
        builtins.throw "shrinker.choicePaths: empty choice list at ${prefix}"
      else
      [ prefix ]
    else if builtins.isAttrs value then
      lib.concatLists (lib.mapAttrsToList (n: v: collectChoicePaths "${prefix}.${n}" v) value)
    else if builtins.isFunction value then
      collectChoicePaths prefix (value { inherit lib; })
    else
      [];

  valueAtChecked = target: path: index:
    let
      options = getValueByPath target path;
    in
    if !(builtins.isList options) then
      builtins.throw "shrinker: path ${path} is not a choice list"
    else
      let
        len = builtins.length options;
      in
      if len == 0 then
        builtins.throw "shrinker: empty choice list at ${path}"
      else if index < 0 || index >= len then
        builtins.throw "shrinker: index ${toString index} out of range for ${path} (0..${toString (len - 1)})"
      else
        builtins.elemAt options index;

in
{
  # apply : target -> fuzzed -> choices_override -> attrset
  #
  # Apply choice overrides to fuzzed output. For each path in choices_override,
  # replace the fuzzed value with the value at the specified index in the target's
  # option list. Paths not in choices_override are left unchanged.
  #
  # Identity when choices_override is empty: apply target fuzzed {} == fuzzed.
  #
  # Example:
  #   target = { memorySize = [ 512 1024 2048 4096 ]; enable = [ false true ]; };
  #   fuzzed  = { memorySize = 2048; enable = true; };
  #   apply target fuzzed { ".memorySize" = 0; }
  #   # => { memorySize = 512; enable = true; }
  #
  apply = target: fuzzed: choices_override:
    applyOverrides target fuzzed choices_override;

  # choicePaths : target -> [string]
  #
  # List all choice paths in a target spec. A choice path is a path where the
  # value is a list — i.e., a place where the fuzzer makes a choice.
  #
  # Example:
  #   choicePaths { virtualisation.memorySize = [ 512 1024 2048 ]; services.nginx.enable = bool; }
  #   # => [ ".services.nginx.enable" ".virtualisation.memorySize" ]
  #
  # Returned in alphabetical order for deterministic iteration.
  #
  choicePaths = target:
    let
      paths = lib.naturalSort (collectChoicePaths "" target);
    in
    if builtins.length paths != builtins.length (lib.unique paths) then
      builtins.throw "shrinker.choicePaths: nested and dotted attribute names produce an ambiguous path"
    else
      paths;

  # valueAt : target -> path -> index -> value
  #
  # Get the value at a specific index in a target's option list.
  # Used by the Python orchestrator to understand what each index maps to.
  #
  # Example:
  #   valueAt { memorySize = [ 512 1024 2048 4096 ]; } ".memorySize" 0
  #   # => 512
  #
  valueAt = target: path: index:
    valueAtChecked target path index;

  # optionsFor : target -> path -> [value]
  #
  # Get the full option list for a path in the target spec.
  # Used by the Python orchestrator to know the range of valid indices.
  #
  # Example:
  #   optionsFor { memorySize = [ 512 1024 2048 4096 ]; } ".memorySize"
  #   # => [ 512 1024 2048 4096 ]
  #
  optionsFor = target: path:
    getValueByPath target path;
}
