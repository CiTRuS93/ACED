# Security policy

`0.1.x` is a development preview. Do not supply production credentials or expose
real users through it. Offline conformance does not qualify live isolation,
independent stopping, or unattended operation.

The host owns identity, process isolation, credentials, tool authorization, approvals,
and protected evidence verification. ACED does not intercept every agent tool call.
Do not give an agent broader access than the configured infrastructure can enforce.
Treat repository content, telemetry, feedback, and agent output as untrusted input.

An independent monitor and emergency stop executor must protect exposure while
ACED or the agent is unavailable. Stopping a CLI process is not evidence that its
product effects have stopped.

Report vulnerabilities through a private maintainer or repository security channel.
If no private channel is available, open a public issue requesting one without
including secrets, personal data, or exploit details.
