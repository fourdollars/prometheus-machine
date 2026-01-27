#!/usr/bin/env python3
"""
Prometheus Configuration Library - Handles prometheus.yml generation
"""

import logging
import yaml
from pathlib import Path
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

PROMETHEUS_CONFIG_DIR = "/etc/prometheus"
PROMETHEUS_CONFIG_FILE = f"{PROMETHEUS_CONFIG_DIR}/prometheus.yml"


class PrometheusConfig:
    """Handle Prometheus configuration file generation"""

    def __init__(self, charm):
        self.charm = charm
        self.config = charm.config

    def generate_config(self, scrape_jobs: Dict[str, Any]):
        """Generate prometheus.yml from configuration and scrape jobs

        Args:
            scrape_jobs: Dictionary of scrape jobs from MetricsEndpointConsumer
        """
        logger.info(f"Generating Prometheus configuration with {len(scrape_jobs)} jobs")

        # Build base configuration
        config = {
            "global": self._build_global_config(),
            "scrape_configs": self._build_scrape_configs(scrape_jobs),
        }

        # Write configuration file
        config_path = Path(PROMETHEUS_CONFIG_FILE)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with config_path.open("w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        logger.info(f"Configuration written to {PROMETHEUS_CONFIG_FILE}")

    def _build_global_config(self) -> Dict[str, Any]:
        """Build global configuration section"""
        scrape_interval = self.config.get("scrape-interval", "1m")
        scrape_timeout = self.config.get("scrape-timeout", "10s")
        evaluation_interval = self.config.get("evaluation-interval", "1m")

        return {
            "scrape_interval": scrape_interval,
            "scrape_timeout": scrape_timeout,
            "evaluation_interval": evaluation_interval,
        }

    def _build_scrape_configs(
        self, scrape_jobs: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Build scrape_configs section from relation data

        Args:
            scrape_jobs: Dictionary of jobs from MetricsEndpointConsumer.jobs()

        Returns:
            List of scrape configuration dictionaries
        """
        configs = []

        # Add Prometheus self-monitoring job
        configs.append(self._build_self_monitoring_job())

        # Process jobs from relations
        for job_name, job_data in scrape_jobs.items():
            try:
                scrape_config = self._build_job_config(job_name, job_data)
                if scrape_config:
                    configs.append(scrape_config)
            except Exception as e:
                logger.error(f"Failed to build config for job {job_name}: {e}")

        return configs

    def _build_self_monitoring_job(self) -> Dict[str, Any]:
        """Build self-monitoring scrape job for Prometheus itself"""
        return {
            "job_name": "prometheus",
            "static_configs": [
                {
                    "targets": ["localhost:9090"],
                }
            ],
        }

    def _build_job_config(
        self, job_name: str, job_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build a single scrape job configuration

        Args:
            job_name: Name of the scrape job
            job_data: Job data from MetricsEndpointConsumer

        Returns:
            Scrape job configuration dictionary
        """
        # Extract job information
        metrics_path = job_data.get("metrics_path", "/metrics")
        static_configs = job_data.get("static_configs", [])

        # Process static configs to resolve wildcard targets
        processed_static_configs = []
        for config in static_configs:
            targets = config.get("targets", [])
            labels = config.get("labels", {})

            # Resolve wildcard targets (e.g., "*:9391" becomes actual unit IPs)
            resolved_targets = []
            for target in targets:
                if target.startswith("*:"):
                    # Wildcard target - MetricsEndpointConsumer should have already resolved these
                    # If not, we'll just pass them through
                    resolved_targets.append(target)
                else:
                    resolved_targets.append(target)

            if resolved_targets:
                processed_static_configs.append(
                    {
                        "targets": resolved_targets,
                        "labels": labels,
                    }
                )

        if not processed_static_configs:
            logger.warning(f"No targets found for job {job_name}")
            return None

        scrape_config = {
            "job_name": job_name,
            "metrics_path": metrics_path,
            "static_configs": processed_static_configs,
        }

        # Add relabeling configs if present
        if "relabel_configs" in job_data:
            scrape_config["relabel_configs"] = job_data["relabel_configs"]

        # Add metric relabeling if present
        if "metric_relabel_configs" in job_data:
            scrape_config["metric_relabel_configs"] = job_data["metric_relabel_configs"]

        return scrape_config
