{ lib }:

{ seed, fuzz }:

let
  hash = s: builtins.hashString "sha256" s;

  toInt = s:
    let
      hashNum = lib.foldl' (acc: c:
        lib.mod (acc * 256 + lib.strings.charToInt c) 1000000000
      ) 0 (lib.stringToCharacters (builtins.hashString "sha256" s));
    in
      lib.mod hashNum 1000000;

  choose = name: options:
    let
      n = toInt (seed + name);
      idx = lib.mod n (builtins.length options);
    in
      builtins.elemAt options idx;

  resolve = prefix: value:
    if builtins.isList value then
      choose prefix value

    else if builtins.isAttrs value then
      lib.mapAttrs (n: v: resolve (prefix + "." + n) v) value

    else if builtins.isFunction value then
      resolve prefix (value { inherit seed prefix; })

    else
      value;

  flat = resolve "" fuzz;

  applyConfig = cfg:
    lib.foldlAttrs
      (acc: name: value:
        lib.recursiveUpdate acc
          (lib.setAttrByPath (lib.splitString "." name) (lib.mkForce value))
      )
      {}
      cfg;
in
{
  config = applyConfig flat;
}
