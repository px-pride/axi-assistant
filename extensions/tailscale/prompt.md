# Tailscale Network Access

Tailscale IPs (the 100.x.x.x CGNAT range) may be blocked by the Bash sandbox. If a command targeting a Tailscale IP fails with a network sandbox error, report the error to the user — do not attempt to bypass the sandbox.

## Machine details

Specific Tailscale IPs, hostnames, and machine roles are in the user profile refs (`profile/refs/tech.md`), not in this extension.
