# Security policy

## Supported versions

Security fixes go into the latest release (currently 0.7.x). Older versions are not patched; upgrade with `pip install -U argus-cloud-optimizer`.

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Report it privately through GitHub: <https://github.com/vamshisiddarth/argus/security/advisories/new> ("Report a vulnerability" on the Security tab).

Include what you found, the version, steps to reproduce, and the impact you expect. Do not include real credentials, account ids, or customer data; redact them.

This is a solo-maintained open source project. Reports are handled on a best-effort basis, with no guaranteed response time. Confirmed issues are fixed in a new release and credited in the changelog unless you prefer otherwise.

## Scope notes

- Argus is read-only by design: it never changes cloud resources. A path that makes it write to a customer cloud account is in scope and serious.
- Reports are rendered as self-contained HTML. Injection through resource names, tags or model text into that page is in scope.
- The model provider you configure receives resource names, types, tags and metrics during a scan. That is documented behavior, not a vulnerability.
