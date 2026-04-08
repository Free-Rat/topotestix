# fuzzer-module.nix
{ lib }:

{ seed, fuzz }:

{ config, pkgs, ... }:

let
  hash = s: builtins.hashString "sha256" s;

  toInt = s:
    let
      hex = builtins.substring 0 8 (hash s);
    in
      lib.strings.toIntBase16 hex;

  choose = name: options:
    let
      n = toInt (seed + name);
      idx = lib.mod n (builtins.length options);
    in
      builtins.elemAt options idx;

  # Resolve fuzz spec into actual config values
  resolve = prefix: value:
    if builtins.isList value then
      choose prefix value

    else if builtins.isAttrs value then
      lib.mapAttrs (n: v: resolve (prefix + "." + n) v) value

    else if builtins.isFunction value then
      value { inherit seed prefix pkgs; }

    else
      value;

in
{
  config = resolve "" fuzz;
  options = {};
}
