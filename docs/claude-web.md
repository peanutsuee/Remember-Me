# Claude Web Attachment Networking

A future Claude web attachment flow may hand an attachment to a deployed
Remember-Me upload service without placing raw bytes in model-visible text.
Stage 7C retains this security guidance. Its general Standalone asset API is
not the future Claude one-click attachment workflow and does not provide signed
upload URLs or a deployed service.

Enable `Allow network egress` only when the later one-click attachment-saving
flow is in use.

In `Additional allowed domains`, enter only the hostname of the user's own
Remember-Me service:

- hostname only;
- no `https://`;
- no path;
- no Token;
- no signed URL.

Keep restricted-domain mode and do not enable `All domains`.

Manual upload through the future Dashboard does not require Claude network
access. Diagnostic output and model-visible text must not include complete
hashes, raw file bytes, credentials, or signed URLs.
