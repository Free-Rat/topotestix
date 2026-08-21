# Runner and Shrinker Changes

## Purpose

The RabbitMQ evaluations required two extensions to TopoTestix:

1. properties needed to distinguish predicted contract violations from
   unexpected system or test-harness failures;
2. the shrinker needed to support Nix attributes whose literal names contain
   dots, such as RabbitMQ's `disk_free_limit.absolute` setting.

## Expected-Failure Classification

The property runner now provides `_check_expected`. In addition to ordinary
`passed` and `failed` results, it records:

- `expected_failure` when a deliberately stronger contract raises an
  `AssertionError` under a configuration predicted to violate it;
- `unexpected_pass` when the contract was predicted to fail but passes.

Only assertion failures can be classified as expected. I/O errors, malformed
result data, missing files, command failures, and programming exceptions remain
ordinary failures. This prevents infrastructure defects from being hidden as
successful negative-control results.

This classification supports paired evaluations. A canonical property can
verify RabbitMQ's documented safety behavior, while a stricter property can
express and test a production assumption such as continued write availability
during disk pressure. An `expected_failure` is therefore a classified contract
violation, not a RabbitMQ defect and not automatically a research finding.

Sweep reports aggregate these statuses, and the command-line summary displays
expected failures and unexpected passes explicitly.

## Dotted Nix Attribute Shrinking

TopoTestix records configuration choices as dot-separated paths. The original
shrinker interpreted every dot as a nesting separator. This failed for literal
Nix attribute names used by RabbitMQ:

```nix
services.rabbitmq.configItems."disk_free_limit.absolute"
```

The shrinker now resolves paths by checking progressively joined path
components against attributes that actually exist in the target. Consequently,
choice lookup and override application can shrink RabbitMQ settings such as
`disk_free_limit.absolute`.

The implementation rejects targets where nested and literal dotted attributes
produce the same serialized path. For example, `a.b` and `"a.b"` cannot both be
represented safely as `.a.b`. Rejecting this case prevents the shrinker from
silently changing the wrong configuration value.

Regression tests cover dotted-key lookup, override application, and ambiguity
rejection.

## Design Limitations

The expected-failure mechanism classifies outcomes; it does not establish that
the tested contract is realistic or scientifically interesting. Each evaluation
still requires a justified production assumption, a precise oracle, and positive
and negative controls.

The dotted-key implementation is a compatibility solution for unambiguous paths,
not a complete path-encoding redesign. A future implementation should represent
paths as arrays of components or use an escaped path syntax shared by the fuzzer,
shrinker, CLI, and stored experiment artifacts.

## Suggested Thesis Placement

In the design chapter, present expected failures as part of the property outcome
model and explain why predicted contract violations must remain distinct from
system defects and harness failures. Present shrinking as operating over
configuration choices rather than arbitrary generated values.

In the implementation chapter, describe `_check_expected`, its restriction to
`AssertionError`, status aggregation in reports, and the existing-attribute
navigation used for literal dotted Nix keys. State explicitly that ambiguous
serialized paths are rejected and that structured path components remain future
work.
