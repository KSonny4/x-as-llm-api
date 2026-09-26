# keeper.nomad.hcl — PROD job on the ovh-vps Nomad cluster.
#
# Deploy (tokens NEVER in git — pass via -var):
#   export NOMAD_ADDR=https://nomad.pkubelka.cz
#   export NOMAD_TOKEN=$(bao kv get -field=management secret/projects/NomadSetup/acl)
#   nomad job run \
#     -var=keeper_token="$(bao kv get -field=token secret/projects/pi-infinity-llm/KEEPER_TOKEN)" \
#     -var=keeper_token_next="" \
#     keeper.nomad.hcl
#
# Rotation window: pass -var=keeper_token_next=<NEW> alongside the current
# token (server parallel-accepts both), smoke with both, then run again with
# keeper_token=<NEW> and keeper_token_next="" to revoke the old one.
#
# Smoke (in-alloc: no published port, token never leaves the cluster):
#   ALLOC=$(nomad job allocs -json keeper | jq -r '.[0].ID')
#   nomad alloc exec $ALLOC python3 /srv/keeper/smoke.py
#
# Secrets note: this cluster runs no Vault/Consul, so the bearer reaches the
# alloc via task env (visible to the Nomad management token holder).
# Source of truth stays Bao (secret/projects/pi-infinity-llm/KEEPER_TOKEN,
# versioned — revoked tokens remain recoverable there, never re-accepted).

variable "keeper_token" {
  type = string
}

variable "keeper_token_next" {
  type    = string
  default = ""
}

# ArtificialAnalysis API key for AA-desc open-provider ordering.
# Never in git: pass via -var=aa_api_key="$(bao kv get -field=key
# secret/projects/pi-infinity-llm/ARTIFICIALANALYSIS_API_KEY)".
# Empty (default) = name order, no stale badge (graceful, by design).
# Sent as x-api-key (AA rejects Authorization: Bearer).

variable "aa_api_key" {
  type    = string
  default = ""
}

# Live seed routes as JSON ({"routes": [...]}), rendered at deploy time
# from Bao (secret/projects/pi-infinity-llm/*). Never in git: pass via
# -var=seeds_json="$(...)". Stored in the job spec like KEEPER_TOKEN
# (cluster has no Vault; holder: Nomad management token only).

variable "seeds_json" {
  type    = string
  default = "{\"routes\": []}"
}

# Parent verified driver.docker.volumes.enabled=true on ovh-nomad-fresh.
# Provision this dedicated bind directory before rollout; not allocation-local.
variable "keeper_data_path" {
  type    = string
  default = "/opt/nomad-volumes/keeper"
}

# Required immutable reviewed image; do not accidentally deploy the old image.
variable "keeper_image" {
  type = string
}

variable "public_origin" {
  type    = string
  default = "https://keeper.pkubelka.cz"
}

# Manually issued non-expiring inference-only principal, NEVER admin authority.
variable "keeper_service_token" {
  type = string
}

variable "zencli_image" {
  type = string
}

variable "keeper_zencli_token" {
  type = string
}

job "keeper" {
  datacenters = ["ovh-vps"]
  type        = "service"

  group "keeper" {
    count = 1

    # Durable bind is on this verified node. Moving nodes requires data migration.
    constraint {
      attribute = "${node.unique.name}"
      value     = "ovh-nomad-fresh"
    }

    network {
      mode = "host"
      # Static loopback port: the Cloudflare tunnel ingress for
      # keeper.pkubelka.cz targets http://localhost:8102 on the node.
      # (Cluster pattern: dump-dev/dev-prod use 8100/8101 the same way.)
      port "http" {
        static       = 8102
        to           = 8102
        host_network = "loopback"
      }
    }

    update {
      max_parallel      = 1
      health_check      = "checks"
      min_healthy_time  = "10s"
      healthy_deadline  = "5m"
      progress_deadline = "10m"
      auto_revert       = false
      canary            = 0
    }

    task "server" {
      driver = "docker"
      config {
        network_mode = "host"
        image        = var.keeper_image
        volumes      = ["${var.keeper_data_path}:/var/lib/keeper"]
        ports        = ["http"]
        force_pull   = true
      }

      env {
        PORT                       = "8102"
        BIND                       = "127.0.0.1"
        KEEPER_TOKEN               = var.keeper_token
        KEEPER_TOKEN_NEXT          = var.keeper_token_next
        ARTIFICIALANALYSIS_API_KEY = var.aa_api_key
        SEED_FILE                  = "${NOMAD_SECRETS_DIR}/seeds.json"
        PROBE_DB                   = "/var/lib/keeper/probe.db"
        AVAILABILITY_DB            = "/var/lib/keeper/availability.db"
        AA_CACHE                   = "/var/lib/keeper/aa-coding.json"
        FEEDBACK_LOG               = "/var/lib/keeper/legacy-feedback.jsonl"
        PUBLIC_ORIGIN              = var.public_origin
        KEEPER_SERVICE_TOKEN       = var.keeper_service_token
        KEEPER_ZENCLI_TOKEN        = var.keeper_zencli_token
        KEEPER_ZENCLI_SOCKET       = "/alloc/data/keeper-zencli/http.sock"
      }

      template {
        data        = var.seeds_json
        destination = "${NOMAD_SECRETS_DIR}/seeds.json"
        change_mode = "restart"
      }

      resources {
        cpu    = 200
        memory = 128
      }

      service {
        name     = "keeper"
        port     = "http"
        provider = "nomad"
        check {
          type     = "http"
          path     = "/healthz"
          interval = "30s"
          timeout  = "5s"
        }
      }
    }
    # Docker bridge restores the controlled CLI egress path; no CNI/internal TCP.
    # Only private HTTP IPC under shared /alloc/data, no host/seed/DB mounts.
    task "zencli" {
      driver = "docker"
      config {
        image           = var.zencli_image
        network_mode    = "bridge"
        force_pull      = true
        readonly_rootfs = true
        cap_drop        = ["ALL"]
        security_opt    = ["no-new-privileges"]
        # Nomad's Docker driver uses mount blocks, not Docker CLI --tmpfs.
        # Docker tmpfs mounts default to nosuid,nodev,noexec; verify on-node.
        mount {
          type   = "tmpfs"
          target = "/tmp"
          tmpfs_options {
            size = 536870912
            mode = 1023 # decimal representation of Unix 01777
          }
        }
      }
      env {
        KEEPER_ZENCLI_TOKEN  = var.keeper_zencli_token
        KEEPER_ZENCLI_SOCKET = "/alloc/data/keeper-zencli/http.sock"
      }
      resources {
        cpu    = 500
        memory = 1024
      }
    }
  }
}
