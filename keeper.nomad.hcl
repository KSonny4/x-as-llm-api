# keeper.nomad.hcl — PROD job (Nomad, not Coolify). Deploy-ready; adjust
# image/region/datacenter/vault paths at deploy time with the Nomad owner.
# Secrets reach the alloc from Bao (OpenBao KVv2 at BAO_ADDR; NomadSetup
# acl/registry in Bao hold cluster access). Exact vault stanza per cluster.
job "keeper" {
  datacenters = ["dc1"]
  type        = "service"

  group "keeper" {
    count = 1

    task "server" {
      driver = "docker"
      config {
        image = "registry.local/keeper:2-skeleton"
        ports = ["http"]
      }

      # Bao-backed secret (KVv2). Field `token` under
      # secret/projects/pi-multi-providers/KEEPER_TOKEN.
      template {
        data        = <<EOH
KEEPER_TOKEN={{ with secret "secret/data/projects/pi-multi-providers/KEEPER_TOKEN" }}{{ .Data.data.token }}{{ end }}
PORT=8080
EOH
        destination = "secrets/keeper.env"
        env         = true
      }

      resources {
        cpu    = 200
        memory = 128
      }

      service {
        name = "keeper"
        port = "http"
        check {
          type     = "http"
          path     = "/healthz"
          interval = "30s"
          timeout  = "5s"
        }
      }
    }

    network {
      port "http" {
        to = 8080
      }
    }
  }
}
