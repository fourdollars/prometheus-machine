# Prometheus Machine Charm

[![GitHub](https://img.shields.io/badge/GitHub-fourdollars/prometheus--machine-blue.svg)](https://github.com/fourdollars/prometheus-machine)
[![Charmhub](https://charmhub.io/prometheus-machine/badge.svg)](https://charmhub.io/prometheus-machine)

A Juju machine charm for deploying Prometheus on bare metal, VMs, and LXD containers.

## Features

- **Machine Deployment**: Runs on LXD, OpenStack, MAAS, and bare metal
- **Automatic Installation**: Downloads and installs Prometheus v2.53.0 (configurable)
- **Metrics Scraping**: Consumes metrics via `prometheus_scrape` interface
- **Dynamic Configuration**: Automatically updates scrape targets when relations change
- **Systemd Integration**: Managed as a systemd service with auto-restart
- **Configurable**: Retention, scraping intervals, ports, and more

## Quick Start

### Deploy Prometheus

```bash
juju deploy ./prometheus-machine_amd64.charm prometheus
```

### Integrate with Applications

```bash
# Integrate with any application providing prometheus_scrape interface
juju integrate prometheus:metrics-endpoint concourse:monitoring
```

### Access Prometheus UI

```bash
# Get Prometheus IP
juju status prometheus

# Access at http://<prometheus-ip>:9090
```

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `prometheus-version` | string | `2.53.0` | Prometheus version to install |
| `listen-address` | string | `0.0.0.0:9090` | Web UI and API listen address |
| `retention-time` | string | `15d` | Data retention period |
| `retention-size` | string | `0` | Max storage size (0=unlimited) |
| `external-url` | string | `` | External URL for Prometheus |
| `log-level` | string | `info` | Log level (debug/info/warn/error) |
| `enable-admin-api` | boolean | `false` | Enable admin API |
| `scrape-interval` | string | `1m` | Default scrape interval |
| `scrape-timeout` | string | `10s` | Default scrape timeout |
| `evaluation-interval` | string | `1m` | Rule evaluation interval |

### Examples

```bash
# Change retention period
juju config prometheus retention-time=30d

# Adjust scraping frequency
juju config prometheus scrape-interval=30s

# Enable debug logging
juju config prometheus log-level=debug
```

## Architecture

```
┌─────────────────────────────────────┐
│         Prometheus Unit             │
│  ┌──────────────────────────────┐   │
│  │  /usr/local/bin/prometheus   │   │
│  │  Port: 9090                  │   │
│  └──────────────────────────────┘   │
│                                     │
│  Config: /etc/prometheus/           │
│  Data:   /var/lib/prometheus/       │
│  User:   prometheus                 │
└─────────────────────────────────────┘
            │
            │ prometheus_scrape relation
            │
    ┌───────┴────────┐
    │                │
┌───▼───┐      ┌─────▼──┐
│App 1  │      │ App 2  │
│:9391  │      │:9100   │
└───────┘      └────────┘
```

## Relations

### Provides

- **`grafana-source`**: Datasource for Grafana
- **`prometheus-peers`**: Peer relation (reserved for future HA)

### Requires

- **`metrics-endpoint`**: Consumes metrics from applications (interface: `prometheus_scrape`)

## File Structure

```
prometheus-machine/
├── charmcraft.yaml          # Build configuration
├── metadata.yaml            # Charm metadata & relations
├── config.yaml              # Configuration options
├── requirements.txt         # Python dependencies
├── src/
│   └── charm.py             # Main charm logic
└── lib/
    ├── prometheus_installer.py  # Installation & service management
    └── prometheus_config.py     # Configuration generation
```

## Implementation Details

### Installation Process

1. Creates `prometheus` user and group
2. Downloads Prometheus binary from GitHub releases
3. Installs to `/usr/local/bin/prometheus`
4. Creates systemd service
5. Sets up directories with proper permissions

### Metrics Collection

- Uses `MetricsEndpointConsumer` from `prometheus_scrape` library
- Automatically discovers scrape targets from related applications
- Regenerates `prometheus.yml` on target changes
- Restarts service to apply new configuration

### Systemd Service

```ini
[Unit]
Description=Prometheus
After=network-online.target

[Service]
Type=simple
User=prometheus
Group=prometheus
ExecStart=/usr/local/bin/prometheus \
    --config.file=/etc/prometheus/prometheus.yml \
    --storage.tsdb.path=/var/lib/prometheus \
    --web.listen-address=0.0.0.0:9090 \
    --storage.tsdb.retention.time=15d
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## Verification

### Check Service Status

```bash
juju ssh prometheus/0 -- sudo systemctl status prometheus
```

### View Configuration

```bash
juju ssh prometheus/0 -- cat /etc/prometheus/prometheus.yml
```

### Check Scrape Targets

```bash
# Get Prometheus IP
PROM_IP=$(juju status prometheus --format=json | jq -r '.applications.prometheus.units | to_entries[0].value."public-address"')

# Query targets API
curl http://$PROM_IP:9090/api/v1/targets | jq .
```

### Query Metrics

```bash
# Query specific metric
curl "http://$PROM_IP:9090/api/v1/query?query=up"
```

## Tested With

- **Juju**: 3.6.13
- **Ubuntu**: 24.04 LTS
- **Clouds**: LXD (localhost)
- **Applications**: Concourse CI Machine Charm

## Example: Integration with Concourse CI

```bash
# Deploy PostgreSQL (required by Concourse)
juju deploy postgresql --channel 16/stable

# Deploy Concourse
juju deploy concourse-ci-machine concourse --config mode=auto
juju integrate concourse:postgresql postgresql:database

# Deploy Prometheus
juju deploy prometheus-machine prometheus

# Integrate for metrics collection
juju integrate prometheus:metrics-endpoint concourse:monitoring

# Wait for deployment
juju status --watch 5s

# Access Prometheus UI
# http://<prometheus-ip>:9090
```

## Troubleshooting

### Service Won't Start

```bash
# Check logs
juju ssh prometheus/0 -- sudo journalctl -u prometheus -n 50

# Verify configuration
juju ssh prometheus/0 -- /usr/local/bin/promtool check config /etc/prometheus/prometheus.yml
```

### No Targets Showing

```bash
# Check relations
juju status --relations

# Verify metrics-endpoint relation exists
juju integrate prometheus:metrics-endpoint <app>:monitoring
```

### Configuration Not Updating

```bash
# Trigger config-changed hook
juju config prometheus scrape-interval=1m
```

## Development

### Building from Source

```bash
# Clone repository
cd prometheus-machine

# Build charm
charmcraft pack

# Deploy locally
juju deploy ./prometheus-machine_amd64.charm
```

### Testing

```bash
# Deploy test environment
juju add-model test
juju deploy ./prometheus-machine_amd64.charm prometheus

# Verify installation
juju ssh prometheus/0 -- /usr/local/bin/prometheus --version
```

## Limitations

- Single-unit deployment only (no HA yet)
- LXD, OpenStack, MAAS, bare metal only (not Kubernetes)
- Manual target configuration requires SSH access

## Future Enhancements

- High availability with Prometheus federation
- Alert manager integration
- Recording rules support
- TLS/authentication support
- Grafana automatic datasource registration

## License

Apache 2.0

## Support

For issues and questions:
- File issues in the charm repository
- Check Juju discourse for general Juju questions
- Prometheus documentation: https://prometheus.io/docs/
