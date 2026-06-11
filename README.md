<div align="center">
<a href="https://www.vantagecompute.ai/">
  <img src="https://vantage-compute-public-assets.s3.us-east-1.amazonaws.com/branding/vantage-logo-text-black-horz.png" alt="Vantage Compute Logo" width="100" style="margin-bottom: 0.5em;"/>
</a>
</div>
<div align="center">

# Vantage Agent Charmed Operator
A Juju charm for installing and operating the Vantage Agent snap.

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![Juju](https://img.shields.io/badge/juju-charm-orange.svg)](https://juju.is/)
[![Charmcraft](https://img.shields.io/badge/charmcraft-4.x-purple.svg)](https://canonical-charmcraft.readthedocs-hosted.com/)

![Publish charm](https://img.shields.io/github/actions/workflow/status/vantagecompute/vantage-agent-charmed-operator/publish-charm.yaml?label=publish&logo=github&style=plastic)
![GitHub Issues](https://img.shields.io/github/issues/vantagecompute/vantage-agent-charmed-operator?label=issues&logo=github&style=plastic)
![Pull Requests](https://img.shields.io/github/issues-pr/vantagecompute/vantage-agent-charmed-operator?label=pull-requests&logo=github&style=plastic)
![GitHub Contributors](https://img.shields.io/github/contributors/vantagecompute/vantage-agent-charmed-operator?logo=github&style=plastic)

</br>

## Quick Start

</div>

### Pack the charm

```bash
# Install the local development environment
just env

# Build a local charm artifact with LXD
just pack
```

The pack recipe runs `charmcraft pack --use-lxd` and produces a platform-specific
`.charm` artifact, such as `vantage-agent_ubuntu@24.04-amd64.charm`.

### Deploy locally

```bash
juju deploy ./vantage-agent_ubuntu@24.04-amd64.charm
```

This is a subordinate charm. Relate it to the principal unit that should run the
Vantage Agent:

```bash
juju integrate vantage-agent <principal-application>
```

Configure credentials with a single action call. The charm stores all three
values in one Juju secret, then uses that secret to download and configure the
snap:

```bash
juju run vantage-agent/0 configure-credentials \
  --client-id "<cluster-client-id>" \
  --client-secret "<cluster-client-secret>" \
  --vantage-url "https://app.dev.vantagecompute.ai"
```

You can also precreate the secret and pass its ID as charm config:

```bash
juju add-secret vantage-agent-configuration-credentials \
  vantage-url="https://app.dev.vantagecompute.ai" \
  client-id="<cluster-client-id>" \
  client-secret="<cluster-client-secret>"

juju grant-secret vantage-agent-configuration-credentials vantage-agent
juju config vantage-agent configuration-credentials-secret-id="<secret-id>"
```

## Configuration

| Option | Description |
| --- | --- |
| `configuration-credentials-secret-id` | Optional Juju secret ID containing `vantage-url`, `client-id`, and `client-secret`; the secret must be granted to this application. |

The charm downloads `vantage-agent.snap` from the Vantage artifacts distribution
using the same client-credentials and bearer-token flow used by Vantage CLI.

## Development

```bash
# Regenerate uv.lock
just lock

# Install dependencies
just env

# Run tests
just test

# Show the current project version
just version
```

The project is managed with `uv`. Runtime and development dependencies live in
`pyproject.toml`; `requirements.txt` is intentionally not generated or used.

## Release

Publishing runs from the `Publish charm` GitHub Actions workflow when a `v*` tag
is pushed.

Prerequisite repository settings:

- Secret `CHARMCRAFT_AUTH`: exported Charmhub credentials from `charmcraft login --export`.
- Optional variable `CHARMHUB_CHANNEL`: release channel, defaulting to `latest/edge`.

Create a release with:

```bash
just release 0.1.0
```

The release command bumps `pyproject.toml`, updates `uv.lock`, commits the
change, creates tag `v0.1.0`, and pushes the commit and tag. The tag workflow
verifies the tag matches the `pyproject.toml` version, packs the charm with
`charmcraft pack --use-lxd`, and uploads it to Charmhub.

## Support

- **Issues**: [GitHub Issues](https://github.com/vantagecompute/vantage-agent-charmed-operator/issues)
- **Email**: [info@vantagecompute.ai](mailto:info@vantagecompute.ai)

---

**Made by [Vantage Compute](https://vantagecompute.ai)**
