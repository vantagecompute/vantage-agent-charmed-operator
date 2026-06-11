"""Vantage Agent Charmed Operator

This library provides the `VantageAgentCharmedOperator` class that encapsulates all event handling and operational logic required
to manage a Snapped Vantage Agent within a Juju charm.
"""

import json
import logging
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional, Union
from urllib import parse

import httpx
import ops

logger = logging.getLogger()


class VantageAgentCharmError(Exception):
    """Exception raised by the VantageAgentCharm class."""

    pass


class SnapperSysCallError(Exception):
    """Raise exception from syscall execution."""

    pass


class VantageAgentCharmedOperator(ops.Object):
    """Vantage Agent Charm Operator."""

    _CREDENTIAL_KEYS = ["vantage-url", "client-id", "client-secret"]
    _CREDENTIALS_SECRET_CONFIG = "configuration-credentials-secret-id"
    _CREDENTIALS_SECRET_LABEL = "vantage-agent-configuration-credentials"
    _SNAP_BASE_URL = "https://vantage-artifacts.vantagecompute.ai/snaps/vantage-agent-snap"
    _SNAP_CHANNEL = "latest"
    _KEYCLOAK_TOKEN_PATH = "/realms/vantage/protocol/openid-connect/token"

    def __init__(self, charm: ops.CharmBase, snap_name: str):
        """Initialize the VantageAgentCharmedOperator."""
        super().__init__(charm, None)
        self._charm = charm
        self._snap_path = Path("/usr/bin/snap")
        self._snap_name = snap_name

        for event, handler in [
            (self._charm.on.install, self._on_install),
            (self._charm.on.config_changed, self._on_config_changed),
            (self._charm.on.configure_credentials_action, self._on_configure_credentials),
            (self._charm.on.update_status, self._on_update_status),
            (self._charm.on.stop, self._on_stop),
            (self._charm.on.remove, self._on_remove),
        ]:
            self._charm.framework.observe(event, handler)

    def _on_install(self, event: ops.InstallEvent) -> None:
        """Install and configure the snap when credentials are already available."""
        logger.debug(f"## Processing install event for {self._snap_name}.")
        try:
            self.configure_snap()
        except VantageAgentCharmError as exc:
            self._charm.unit.status = ops.BlockedStatus(str(exc))
        except Exception as exc:
            logger.error(f"## Error installing {self._snap_name}: {exc}")
            self._charm.unit.status = ops.BlockedStatus(
                f"Error installing the snap for {self._snap_name}"
            )
            event.defer()

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """Reconfigure the snap when a precreated credentials secret is configured."""
        logger.debug(f"## Processing config changed event: {self._snap_name}.")
        try:
            self.configure_snap()
        except VantageAgentCharmError as exc:
            self._charm.unit.status = ops.BlockedStatus(str(exc))
        except Exception as exc:
            logger.error(f"## Error configuring {self._snap_name}: {exc}")
            self._charm.unit.status = ops.BlockedStatus(
                f"Error configuring the snap for {self._snap_name}"
            )
            event.defer()

    def _on_configure_credentials(self, event: ops.ActionEvent) -> None:
        """Create/update one credentials secret, then install and configure the snap."""
        logger.debug("## Processing configure-credentials action for %s.", self._snap_name)
        if self._configured_credentials_secret_id():
            event.fail(
                f"{self._CREDENTIALS_SECRET_CONFIG} is set; update that precreated secret "
                "directly or unset the config before using this action"
            )
            return

        if not self.model.unit.is_leader():
            event.fail("configure-credentials must be run on the leader unit")
            return

        credentials = {key: str(event.params.get(key, "")).strip() for key in self._CREDENTIAL_KEYS}
        missing = [key for key, value in credentials.items() if not value]
        if missing:
            event.fail(f"Missing required parameters: {', '.join(missing)}")
            return

        try:
            secret = self._action_credentials_secret()
            if secret:
                secret.set_content(credentials)
            else:
                secret = self.model.app.add_secret(
                    credentials,
                    label=self._CREDENTIALS_SECRET_LABEL,
                    description="Vantage Agent configuration credentials",
                )

            self.configure_snap(credentials)
        except Exception as exc:
            logger.error("## Error applying configured credentials: %s", exc)
            self._charm.unit.status = ops.BlockedStatus(
                f"Error configuring the snap for {self._snap_name}"
            )
            event.fail(str(exc))
            return

        event.set_results({self._CREDENTIALS_SECRET_CONFIG: secret.id})

    def _on_stop(self, event: ops.StopEvent):
        """Perform stop operations."""
        logger.debug(f"## Processing stop event for {self._snap_name}.")
        self._charm.unit.status = ops.MaintenanceStatus()
        self.run_snap_service("stop")

    def _on_remove(self, event: ops.RemoveEvent):
        """Perform remove operations."""
        logger.debug(f"## Processing remove event for {self._snap_name}.")
        self.remove_snap()

    def _on_update_status(
        self,
        event: Optional[Union[ops.ConfigChangedEvent, ops.UpdateStatusEvent, ops.InstallEvent]],
    ) -> None:
        """Update the charm status based on snap state."""
        try:
            self._credentials()
        except VantageAgentCharmError as exc:
            self._charm.unit.status = ops.BlockedStatus(str(exc))
            return

        if self.model.unit.is_leader():
            if self._is_snap_active:
                self._charm.unit.status = ops.ActiveStatus()
            else:
                self._charm.unit.status = ops.BlockedStatus("Cannot start snap.")
        else:
            self._charm.unit.status = ops.ActiveStatus(f"{self._snap_name} status: standby")

    def configure_snap(self, credentials: Optional[dict[str, str]] = None) -> None:
        """Install and configure the snap using credentials from one Juju secret."""
        credentials = credentials or self._credentials()
        if not self._is_snap_installed:
            logger.debug(f"## Snap: {self._snap_name} not installed, installing")
            self.install_snap(credentials)

        snap_configs = self._snap_config(credentials)
        logger.debug("Snap config keys: %s", sorted(snap_configs))
        self.run_snap_service("stop")
        for key, value in snap_configs.items():
            self._sys_exec(self._snap_path, "set", self._snap_name, f"{key}={value}")

        if self.model.unit.is_leader():
            self.run_snap_service("start")

        self._on_update_status(None)

    def _snap_config(self, credentials: dict[str, str]) -> dict[str, str]:
        """Return snap configuration derived from credentials secret content."""
        return {
            "vantage-url": credentials["vantage-url"],
            "cluster-client-id": credentials["client-id"],
            "cluster-client-secret": credentials["client-secret"],
        }

    def _configured_credentials_secret_id(self) -> str:
        """Return the precreated credentials secret ID configured by the user."""
        return str(self._charm.config.get(self._CREDENTIALS_SECRET_CONFIG) or "").strip()

    def _action_credentials_secret(self) -> Optional[ops.Secret]:
        """Return the charm-owned credentials secret created by the action, if present."""
        try:
            return self.model.get_secret(label=self._CREDENTIALS_SECRET_LABEL)
        except ops.SecretNotFoundError:
            return None

    def _credentials_secret(self) -> Optional[ops.Secret]:
        """Return the configured or charm-owned credentials secret."""
        secret_id = self._configured_credentials_secret_id()
        try:
            if secret_id:
                return self.model.get_secret(id=secret_id)
            return self.model.get_secret(label=self._CREDENTIALS_SECRET_LABEL)
        except ops.SecretNotFoundError:
            return None

    def _credentials(self) -> dict[str, str]:
        """Return Vantage credentials from a single Juju secret."""
        secret = self._credentials_secret()
        if not secret:
            raise VantageAgentCharmError(self._missing_credentials_message())

        content = secret.get_content(refresh=True)
        missing = [key for key in self._CREDENTIAL_KEYS if not content.get(key)]
        if missing:
            raise VantageAgentCharmError(
                f"Credentials secret is missing required keys: {', '.join(missing)}"
            )
        return {key: str(content[key]) for key in self._CREDENTIAL_KEYS}

    def _missing_credentials_message(self) -> str:
        """Return a status message for missing credentials."""
        return (
            "Run configure-credentials or set configuration-credentials-secret-id "
            "to a Juju secret containing vantage-url, client-id, and client-secret"
        )

    @property
    def _is_snap_installed(self) -> bool:
        """Return True if the snap is installed, else False."""
        logger.debug(f"### Checking if snap {self._snap_name} is installed")
        try:
            self._sys_exec(self._snap_path, "list", self._snap_name)
            return True
        except SnapperSysCallError:
            return False

    @property
    def _is_snap_active(self) -> bool:
        """Return True if the snap service is active, else False."""
        logger.debug(f"### Checking active status for {self._snap_name}.daemon")
        try:
            status_output = self._sys_exec(self._snap_path, "services", f"{self._snap_name}.daemon")
        except SnapperSysCallError:
            return False

        for line in status_output.splitlines():
            if line.startswith(f"{self._snap_name}.daemon"):
                parts = line.split()
                if len(parts) >= 4 and parts[2] == "active":
                    return True
        return False

    def install_snap(self, credentials: dict[str, str]) -> None:
        """Download, then install or refresh the snap from Vantage artifacts."""
        snap_file = self._download_snap(credentials)
        if not self._is_snap_installed:
            logger.debug(f"### Installing {self._snap_name}.")
            self._sys_exec(self._snap_path, "install", "--classic", "--dangerous", snap_file)
        else:
            logger.debug(f"### Refreshing {self._snap_name} (already installed).")
            self._sys_exec(self._snap_path, "refresh", "--classic", "--dangerous", snap_file)

    def _download_snap(self, credentials: dict[str, str]) -> str:
        """Download the snap artifact using client credentials."""
        auth_token = self._fetch_auth_token(credentials)
        snap_arch = self._sys_exec("dpkg", "--print-architecture").strip()
        snap_url = f"{self._SNAP_BASE_URL}/{snap_arch}/{self._SNAP_CHANNEL}/{self._snap_name}.snap"

        logger.debug("Downloading %s snap from %s", self._snap_name, snap_url)
        snap_path = Path(tempfile.gettempdir()) / f"{self._snap_name}.snap"
        try:
            with httpx.Client() as client:
                response = client.get(
                    snap_url,
                    headers={"Authorization": f"Bearer {auth_token}"},
                    timeout=120.0,
                    follow_redirects=True,
                )
                response.raise_for_status()
                snap_path.write_bytes(response.content)
        except Exception as exc:
            raise VantageAgentCharmError(f"failed to download snap artifact: {exc}")

        return str(snap_path)

    def _fetch_auth_token(self, credentials: dict[str, str]) -> str:
        """Fetch a client-credentials token for the snap artifact request."""
        token_url = self._token_url(credentials["vantage-url"])
        logger.debug("Getting JWT token from %s", token_url)
        try:
            with httpx.Client() as client:
                response = client.post(
                    token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": credentials["client-id"],
                        "client_secret": credentials["client-secret"],
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=30.0,
                )
                response.raise_for_status()
                token_response = response.json()
        except Exception as exc:
            raise VantageAgentCharmError(f"failed to fetch artifact auth token: {exc}")

        token = token_response.get("access_token")
        if not token:
            raise VantageAgentCharmError("artifact auth token response did not include access_token")
        return str(token)

    def _token_url(self, vantage_url: Optional[str] = None) -> str:
        """Derive the OIDC token endpoint from a Vantage app URL."""
        return f"{self._oidc_base_url(vantage_url)}{self._KEYCLOAK_TOKEN_PATH}"

    def _oidc_base_url(self, vantage_url: Optional[str] = None) -> str:
        """Derive the OIDC base URL from a Vantage app URL."""
        vantage_url = str(vantage_url or self._credentials()["vantage-url"]).rstrip("/")
        if "://" not in vantage_url:
            vantage_url = f"https://{vantage_url}"

        parsed = parse.urlparse(vantage_url)
        hostname = parsed.hostname or ""
        if hostname.startswith("app."):
            auth_hostname = f"auth.{hostname.removeprefix('app.')}"
        elif hostname.startswith("apis."):
            auth_hostname = f"auth.{hostname.removeprefix('apis.')}"
        else:
            auth_hostname = f"auth.{hostname}"

        return f"{parsed.scheme}://{auth_hostname}"

    def get_snap_config(self) -> dict:
        """Get the current snap configuration as a dictionary."""
        logger.debug(f"#### Fetching current config for {self._snap_name}.")
        try:
            config_output = self._sys_exec(self._snap_path, "get", "-d", self._snap_name)
        except SnapperSysCallError:
            return {}
        try:
            snap_config = json.loads(config_output)
        except json.JSONDecodeError:
            logger.error("#### Error decoding snap config")
            return {}
        return snap_config

    def remove_snap(self) -> None:
        """Remove the snap from the system."""
        logger.debug(f"### Removing {self._snap_name}.")
        self._sys_exec(self._snap_path, "remove", self._snap_name)

    def run_snap_service(self, service: str) -> None:
        """Run a snap service (e.g., start/stop daemon)."""
        logger.debug(f"### Running {self._snap_name}.{service}")
        try:
            self._sys_exec(self._snap_path, "run", f"{self._snap_name}.{service}")
        except SnapperSysCallError as e:
            logger.error(f"Error running {self._snap_name}.{service}: {e}")

    @staticmethod
    def _sys_exec(*cmd: Any) -> str:
        """Execute a system command and return its output."""
        str_cmd = [str(p) for p in cmd]
        logger.debug(f"-----> Running command in subprocess: {shlex.join(str_cmd)}")
        try:
            result = subprocess.run(str_cmd, capture_output=True, check=False)
        except Exception as exc:
            message = f"{shlex.join(str_cmd)} - {exc}"
            logger.error(f"Invalid system command: {message}")
            raise SnapperSysCallError(f"System command failed: {message}")

        if result.returncode != 0:
            err = result.stderr.decode("utf-8")
            message = f"{shlex.join(str_cmd)} - {err}"
            logger.error(f"Error executing command: {message}")
            raise SnapperSysCallError(f"System command failed: {message}")

        out = result.stdout.decode("utf-8")
        logger.debug(f"-----> Command succeeded: {out.strip()}")
        return out


class VantageAgentCharm(ops.CharmBase):
    """Charm entrypoint for the Vantage Agent snap."""

    def __init__(self, *args: Any):
        """Initialize charm event handling."""
        super().__init__(*args)
        self._operator = VantageAgentCharmedOperator(self, "vantage-agent")


if __name__ == "__main__":
    ops.main(VantageAgentCharm)
