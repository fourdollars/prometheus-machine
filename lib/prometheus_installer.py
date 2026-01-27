#!/usr/bin/env python3
"""
Prometheus Installer Library - Handles downloading and installing Prometheus
"""

import json
import logging
import os
import pwd
import grp
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Installation paths
PROMETHEUS_USER = "prometheus"
PROMETHEUS_GROUP = "prometheus"
PROMETHEUS_INSTALL_DIR = "/opt/prometheus"
PROMETHEUS_DATA_DIR = "/var/lib/prometheus"
PROMETHEUS_CONFIG_DIR = "/etc/prometheus"
PROMETHEUS_BIN = "/usr/local/bin/prometheus"
PROMTOOL_BIN = "/usr/local/bin/promtool"


class PrometheusInstaller:
    """Handle Prometheus installation and lifecycle"""

    def __init__(self, charm):
        self.charm = charm
        self.unit = charm.unit
        self.config = charm.config

    def setup_user_and_directories(self):
        """Create prometheus user and required directories"""
        logger.info("Creating prometheus user and directories")

        # Create prometheus group if it doesn't exist
        try:
            grp.getgrnam(PROMETHEUS_GROUP)
        except KeyError:
            subprocess.run(
                ["groupadd", "--system", PROMETHEUS_GROUP],
                check=True,
                capture_output=True,
            )
            logger.info(f"Created group {PROMETHEUS_GROUP}")

        # Create prometheus user if it doesn't exist
        try:
            pwd.getpwnam(PROMETHEUS_USER)
        except KeyError:
            subprocess.run(
                [
                    "useradd",
                    "--system",
                    "--gid",
                    PROMETHEUS_GROUP,
                    "--no-create-home",
                    "--shell",
                    "/bin/false",
                    PROMETHEUS_USER,
                ],
                check=True,
                capture_output=True,
            )
            logger.info(f"Created user {PROMETHEUS_USER}")

        # Create directories
        directories = [
            PROMETHEUS_INSTALL_DIR,
            PROMETHEUS_DATA_DIR,
            PROMETHEUS_CONFIG_DIR,
        ]

        for directory in directories:
            Path(directory).mkdir(parents=True, exist_ok=True)
            os.chown(
                directory,
                pwd.getpwnam(PROMETHEUS_USER).pw_uid,
                grp.getgrnam(PROMETHEUS_GROUP).gr_gid,
            )
            logger.info(f"Created directory {directory}")

    def install_prometheus(self, version: str):
        """Download and install Prometheus binary"""
        logger.info(f"Installing Prometheus version {version}")

        # Construct download URL
        arch = self._get_architecture()
        url = (
            f"https://github.com/prometheus/prometheus/releases/download/"
            f"v{version}/prometheus-{version}.linux-{arch}.tar.gz"
        )

        logger.info(f"Downloading from {url}")

        # Download to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tmp_file:
            tmp_path = tmp_file.name
            subprocess.run(
                ["curl", "-L", "-o", tmp_path, url],
                check=True,
                capture_output=True,
            )

        try:
            # Extract tarball
            logger.info(f"Extracting Prometheus tarball")
            with tarfile.open(tmp_path, "r:gz") as tar:
                tar.extractall(path="/tmp")

            # Move binaries to /usr/local/bin
            extracted_dir = f"/tmp/prometheus-{version}.linux-{arch}"

            subprocess.run(
                ["cp", f"{extracted_dir}/prometheus", PROMETHEUS_BIN],
                check=True,
            )
            subprocess.run(
                ["cp", f"{extracted_dir}/promtool", PROMTOOL_BIN],
                check=True,
            )

            # Make binaries executable
            os.chmod(PROMETHEUS_BIN, 0o755)
            os.chmod(PROMTOOL_BIN, 0o755)

            # Copy console libraries and templates
            subprocess.run(
                ["cp", "-r", f"{extracted_dir}/consoles", PROMETHEUS_CONFIG_DIR],
                check=True,
            )
            subprocess.run(
                [
                    "cp",
                    "-r",
                    f"{extracted_dir}/console_libraries",
                    PROMETHEUS_CONFIG_DIR,
                ],
                check=True,
            )

            # Clean up extracted directory
            subprocess.run(["rm", "-rf", extracted_dir], check=True)

            logger.info(f"Prometheus {version} installed successfully")

        finally:
            # Clean up temporary file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def create_systemd_service(self):
        """Create systemd service file for Prometheus"""
        logger.info("Creating Prometheus systemd service")

        # Get configuration values
        listen_address = self.config.get("listen-address", "0.0.0.0:9090")
        retention_time = self.config.get("retention-time", "15d")
        retention_size = self.config.get("retention-size", "0")
        external_url = self.config.get("external-url", "")
        log_level = self.config.get("log-level", "info")
        enable_admin_api = self.config.get("enable-admin-api", False)

        # Build command line arguments
        args = [
            f"--config.file={PROMETHEUS_CONFIG_DIR}/prometheus.yml",
            f"--storage.tsdb.path={PROMETHEUS_DATA_DIR}",
            f"--web.console.templates={PROMETHEUS_CONFIG_DIR}/consoles",
            f"--web.console.libraries={PROMETHEUS_CONFIG_DIR}/console_libraries",
            f"--web.listen-address={listen_address}",
            f"--storage.tsdb.retention.time={retention_time}",
            f"--log.level={log_level}",
        ]

        if retention_size != "0":
            args.append(f"--storage.tsdb.retention.size={retention_size}")

        if external_url:
            args.append(f"--web.external-url={external_url}")

        if enable_admin_api:
            args.append("--web.enable-admin-api")

        # Build ExecStart line with proper line continuations
        exec_start = f"ExecStart={PROMETHEUS_BIN}"
        for arg in args:
            exec_start += f" \\\n    {arg}"

        service_content = f"""[Unit]
Description=Prometheus
Documentation=https://prometheus.io/docs/introduction/overview/
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User={PROMETHEUS_USER}
Group={PROMETHEUS_GROUP}
{exec_start}

Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
"""

        service_path = Path("/etc/systemd/system/prometheus.service")
        service_path.write_text(service_content)
        os.chmod(service_path, 0o644)

        # Reload systemd
        subprocess.run(["systemctl", "daemon-reload"], check=True)

        logger.info("Systemd service created")

    def start_service(self):
        """Start Prometheus service"""
        logger.info("Starting Prometheus service")
        subprocess.run(["systemctl", "enable", "prometheus"], check=True)
        subprocess.run(["systemctl", "start", "prometheus"], check=True)

    def stop_service(self):
        """Stop Prometheus service"""
        logger.info("Stopping Prometheus service")
        subprocess.run(["systemctl", "stop", "prometheus"], check=True)

    def restart_service(self):
        """Restart Prometheus service"""
        logger.info("Restarting Prometheus service")
        subprocess.run(["systemctl", "restart", "prometheus"], check=True)

    def is_service_running(self) -> bool:
        """Check if Prometheus service is running"""
        result = subprocess.run(
            ["systemctl", "is-active", "prometheus"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def is_installed(self) -> bool:
        """Check if Prometheus is installed"""
        return Path(PROMETHEUS_BIN).exists()

    def _get_architecture(self) -> str:
        """Get system architecture for download"""
        arch = os.uname().machine
        if arch == "x86_64":
            return "amd64"
        elif arch == "aarch64":
            return "arm64"
        else:
            raise RuntimeError(f"Unsupported architecture: {arch}")
