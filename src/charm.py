#!/usr/bin/env python3
"""
Prometheus Machine Charm - Deploy Prometheus on machines/VMs
Consumes metrics from applications providing prometheus_scrape interface
"""

import logging
import sys
import requests
from pathlib import Path
from typing import Dict, List, Any

# Add lib to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from ops.charm import CharmBase
from ops.main import main
from ops.model import (
    ActiveStatus,
    WaitingStatus,
    BlockedStatus,
    MaintenanceStatus,
)

# Import prometheus scrape library
try:
    from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointConsumer

    HAS_PROMETHEUS_SCRAPE = True
except ImportError:
    HAS_PROMETHEUS_SCRAPE = False

# Import grafana source library
try:
    from charms.grafana_k8s.v0.grafana_source import GrafanaSourceProvider

    HAS_GRAFANA_SOURCE = True
except ImportError:
    HAS_GRAFANA_SOURCE = False

# Import helper modules
try:
    from prometheus_installer import PrometheusInstaller
    from prometheus_config import PrometheusConfig

    HAS_HELPERS = True
except ImportError:
    HAS_HELPERS = False

# Configure logging
log_handlers = [logging.StreamHandler()]
log_file_path = Path("/var/log/prometheus.log")
if log_file_path.parent.exists() and log_file_path.parent.is_dir():
    try:
        log_handlers.append(logging.FileHandler(log_file_path))
    except (PermissionError, OSError):
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=log_handlers,
)
logger = logging.getLogger("prometheus-machine")


class PrometheusMachineCharm(CharmBase):
    """Main Prometheus Machine Charm class"""

    def __init__(self, *args):
        super().__init__(*args)

        # Check for required libraries
        if not HAS_PROMETHEUS_SCRAPE:
            logger.error("prometheus_scrape library not available")
            self.unit.status = BlockedStatus("Missing prometheus_scrape library")
            return

        if not HAS_HELPERS:
            logger.error("Helper modules not available")
            self.unit.status = BlockedStatus("Missing helper modules")
            return

        # Initialize helpers
        self.installer = PrometheusInstaller(self)
        self.config_manager = PrometheusConfig(self)

        # Initialize MetricsEndpointConsumer
        self.metrics_consumer = MetricsEndpointConsumer(
            self, relation_name="metrics-endpoint"
        )

        # Initialize GrafanaSourceProvider
        if HAS_GRAFANA_SOURCE:
            http_port = self.config.get("http-port", 9090)
            try:
                unit_ip = self.model.get_binding("juju-info").network.bind_address
                prometheus_url = f"http://{unit_ip}:{http_port}"
            except Exception:
                prometheus_url = f"http://localhost:{http_port}"

            self.grafana_source_provider = GrafanaSourceProvider(
                self,
                source_type="prometheus",
                source_url=prometheus_url,
                relation_name="grafana-source",
            )
        else:
            logger.warning("GrafanaSourceProvider not available")
            self.grafana_source_provider = None

        # Register event handlers
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.stop, self._on_stop)

        # Metrics endpoint relation events
        self.framework.observe(
            self.metrics_consumer.on.targets_changed, self._on_targets_changed
        )

    def _on_install(self, event):
        """Install Prometheus during the install hook"""
        logger.info("Running install hook")
        self.unit.status = MaintenanceStatus("Installing Prometheus")

        try:
            # Create prometheus user and directories
            self.installer.setup_user_and_directories()

            # Download and install Prometheus binary
            version = self.config.get("prometheus-version", "2.53.0")
            self.installer.install_prometheus(version)

            # Create systemd service
            self.installer.create_systemd_service()

            # Generate initial configuration
            self.config_manager.generate_config({})

            logger.info("Prometheus installation completed")
            self.unit.status = MaintenanceStatus("Prometheus installed")

        except Exception as e:
            logger.error(f"Installation failed: {e}")
            self.unit.status = BlockedStatus(f"Installation failed: {e}")
            raise

    def _on_config_changed(self, event):
        """Handle configuration changes"""
        logger.info("Configuration changed")

        # Regenerate configuration with new settings
        jobs = self._get_scrape_jobs()
        self.config_manager.generate_config(jobs)

        # Restart service to apply changes
        if self.installer.is_service_running():
            self.installer.restart_service()
            logger.info("Prometheus restarted with new configuration")

        self._update_status()

    def _on_start(self, event):
        """Start Prometheus service"""
        logger.info("Starting Prometheus")

        try:
            self.installer.start_service()
            self._update_status()
        except Exception as e:
            logger.error(f"Failed to start Prometheus: {e}")
            self.unit.status = BlockedStatus(f"Failed to start: {e}")

    def _on_update_status(self, event):
        """Periodic status check"""
        self._update_status()

    def _on_stop(self, event):
        """Stop Prometheus service"""
        logger.info("Stopping Prometheus")
        try:
            self.installer.stop_service()
        except Exception as e:
            logger.error(f"Failed to stop Prometheus: {e}")

    def _on_targets_changed(self, event):
        """Handle changes to scrape targets from related applications"""
        logger.info("Scrape targets changed")

        # Get updated scrape jobs
        jobs = self._get_scrape_jobs()

        # Regenerate configuration
        self.config_manager.generate_config(jobs)

        # Restart service to pick up new targets
        if self.installer.is_service_running():
            self.installer.restart_service()
            logger.info(f"Reloaded configuration with {len(jobs)} scrape jobs")

        self._update_status()

    def _get_scrape_jobs(self) -> Dict[str, Any]:
        """Get scrape jobs from metrics-endpoint relations"""
        jobs = {}

        # Get jobs from MetricsEndpointConsumer
        for job in self.metrics_consumer.jobs():
            job_name = job.get("job_name", "unknown")
            jobs[job_name] = job

        logger.info(f"Retrieved {len(jobs)} scrape jobs from relations")
        return jobs

    def _get_active_targets_from_api(self) -> int:
        """Query Prometheus API to get actual active target count"""
        try:
            listen_address = self.config.get("listen-address", "0.0.0.0:9090")
            # Extract port from listen-address
            port = listen_address.split(":")[-1]

            # Retry logic for Prometheus API (might not be ready immediately after restart)
            import time

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = requests.get(
                        f"http://localhost:{port}/api/v1/targets", timeout=5
                    )
                    if response.status_code == 200:
                        data = response.json()
                        active_targets = data.get("data", {}).get("activeTargets", [])
                        # Exclude self-monitoring (prometheus job) from count
                        non_self_targets = [
                            t
                            for t in active_targets
                            if t.get("labels", {}).get("job") != "prometheus"
                        ]
                        return len(non_self_targets)
                except (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                ):
                    if attempt < max_retries - 1:
                        logger.debug(
                            f"Prometheus API not ready, retrying in 2s (attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(2)
                    continue
        except Exception as e:
            logger.debug(f"Failed to query Prometheus API: {e}")

        return 0

    def _update_status(self):
        """Update unit status based on current state"""
        if not self.installer.is_installed():
            self.unit.status = BlockedStatus("Prometheus not installed")
            return

        if not self.installer.is_service_running():
            self.unit.status = BlockedStatus("Prometheus service not running")
            return

        # Get actual target count from Prometheus API
        # This includes both relation-based and manual targets
        target_count = self._get_active_targets_from_api()

        if target_count == 0:
            self.unit.status = ActiveStatus("Prometheus ready (no targets)")
        else:
            self.unit.status = ActiveStatus(
                f"Prometheus ready (scraping {target_count} targets)"
            )


if __name__ == "__main__":
    main(PrometheusMachineCharm)
