# keeper-alloy.nomad.hcl — metrics shipper: keeper /metrics → Grafana Cloud.
#
# Why this exists: Grafana Cloud has no scrape-job API scope on our tokens,
# so the Cloud cannot pull keeper's bearer-gated /metrics. This Alloy sidecar
# scrapes node-loopback :8102 (same as the tunnel ingress) and remote_writes
# to Hosted Prometheus. The divergent alert rule queries those series.
#
# Register (tokens NEVER in git — pass via -var):
#   export NOMAD_ADDR=https://nomad.pkubelka.cz
#   export NOMAD_TOKEN=$(bao kv get -field=management secret/projects/NomadSetup/acl)
#   nomad job run \
#     -var=keeper_token="$(bao kv get -field=token secret/projects/pi-multi-providers/KEEPER_TOKEN)" \
#     -var=prom_user="$(bao kv get -field=value secret/projects/control-panel/GRAFANA_CLOUD_PROMETHEUS_USERNAME)" \
#     -var=prom_token="<metrics publisher token>" \
#     keeper-alloy.nomad.hcl
#
# Verify: keeper_route_divergent appears in grafanacloud-prom within ~1 min:
#   curl -H "Authorization: Bearer $GRAFANA_TOKEN" \
#     'https://meowlabs.grafana.net/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?query=keeper_route_divergent'
#
# Secret class: same as KEEPER_TOKEN (holder = Nomad management token only;
# source of truth stays Bao). Health signal = series presence in Cloud,
# not a Nomad check (a green alloc that ships nothing is the failure mode).

variable "keeper_token" {
  type = string
}

variable "prom_url" {
  type    = string
  default = "https://prometheus-prod-55-prod-gb-south-1.grafana.net/api/prom/push"
}

variable "prom_user" {
  type = string
}

variable "prom_token" {
  type = string
}

job "keeper-alloy" {
  datacenters = ["ovh-vps"]
  type        = "service"

  group "alloy" {
    count = 1

    network {
      mode = "host"
    }

    task "alloy" {
      driver = "docker"
      config {
        image        = "grafana/alloy:v1.19.2"
        force_pull   = true
        network_mode = "host"
        args = [
          "run",
          "/etc/alloy/config.alloy",
          "--storage.path=${NOMAD_ALLOC_DIR}/data",
          "--server.http.listen-addr=127.0.0.1:12345",
        ]
      }

      template {
        data        = <<EOH
prometheus.scrape "keeper" {
  targets         = [{ "__address__" = "127.0.0.1:8102" }]
  scrape_interval = "30s"
  bearer_token    = "${var.keeper_token}"
  forward_to      = [prometheus.remote_write.cloud.receiver]
}

prometheus.remote_write "cloud" {
  endpoint {
    url = "${var.prom_url}"
    basic_auth {
      username = "${var.prom_user}"
      password = "${var.prom_token}"
    }
  }
}
EOH
        destination = "/etc/alloy/config.alloy"
        change_mode = "restart"
      }

      resources {
        cpu    = 200
        memory = 256
      }
    }
  }
}
