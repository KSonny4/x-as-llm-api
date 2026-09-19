# keeper-probe.nomad.hcl — ON-DEMAND dual prober (Nomad batch job).
#
# Runs probe/dispatch.py in-cluster: L1 curl always, L2 opencode CLI only
# on L1 non-ok; results POST back to keeper /api/v1/probe so the matrix,
# /metrics and the Grafana alert see fresh dual verdicts.
#
# Register (secrets NEVER in git — pass via -var):
#   export NOMAD_ADDR=https://nomad.pkubelka.cz
#   export NOMAD_TOKEN=$(bao kv get -field=management secret/projects/NomadSetup/acl)
#   nomad job run \
#     -var=keeper_token="$(bao kv get -field=token secret/projects/pi-infinity-llm/KEEPER_TOKEN)" \
#     -var=seeds_json="$(cat /tmp/seeds-live.json)" \
#     -var=opencode_auth_json="$(cat ~/.local/share/opencode/auth.json)" \
#     keeper-probe.nomad.hcl
#
# Dispatch on demand (e.g. when L1 fails, or on a schedule you own):
#   nomad job dispatch keeper-probe
# Then: keeper matrix refresh (?refresh=1) shows fresh l2 verdicts.
#
# Zen L1 egress: an `egress` sidecar (sing-box userspace WireGuard to a
# pinned Mullvad relay + HTTP CONNECT on 127.0.0.1:8888) carries ONLY
# opencode.ai traffic (sing-box route rules; rest direct). The probe
# task sets HTTPS_PROXY so urllib L1 + any proxy-aware L2 legs use it;
# NO_PROXY keeps keeper POSTs on loopback. Zero privileges: no
# NET_ADMIN, no TUN device, no node changes. WireGuard identity arrives
# via -var (Bao-held, never git):
#     -var=wg_private_key="$(bao kv get -field=private_key secret/projects/pi-infinity-llm/MULLVAD_WIREGUARD_KEY)" \
#     -var=wg_addresses="$(bao kv get -field=addresses secret/projects/pi-infinity-llm/MULLVAD_WIREGUARD_KEY)" \
#
# Notes: network_mode host so the probe reaches keeper on node loopback
# (:8102) without publishing ports. opencode auth arrives as a templated
# file staged by the entrypoint (same secret class as KEEPER_TOKEN:
# holder = Nomad management token only; source of truth stays local
# opencode login / Bao).

variable "keeper_token" {
  type = string
}

variable "seeds_json" {
  type    = string
  default = "{\"routes\": []}"
}

variable "opencode_auth_json" {
  type    = string
  default = "{}"
}

variable "wg_private_key" {
  type    = string
  default = ""
}

variable "wg_addresses" {
  type    = string
  default = ""
}

variable "wg_peer_public_key" {
  type    = string
  default = "tzYLWgBdwrbbBCXYHRSoYIho4dHtrm+8bdONU1I8xzc="
}

variable "wg_peer_endpoint" {
  type    = string
  default = "185.209.196.74:51820"
}

job "keeper-probe" {
  datacenters = ["ovh-vps"]
  type        = "batch"

  parameterized {
    payload = "optional"
  }

  group "probe" {
    count = 1

    task "probe" {
      driver = "docker"
      config {
        image        = "registry.pkubelka.cz/keeper-probe:main-76660e7"
        force_pull   = true
        network_mode = "host"
      }

      env {
        KEEPER_URL          = "http://127.0.0.1:8102"
        KEEPER_TOKEN        = var.keeper_token
        SEEDS_JSON          = var.seeds_json
        OPENCODE_AUTH_FILE  = "${NOMAD_SECRETS_DIR}/opencode-auth.json"
        HTTPS_PROXY         = "http://127.0.0.1:8888"
        HTTP_PROXY          = "http://127.0.0.1:8888"
        NO_PROXY            = "127.0.0.1,localhost"
      }

      template {
        data        = var.opencode_auth_json
        destination = "${NOMAD_SECRETS_DIR}/opencode-auth.json"
        change_mode = "restart"
      }

      resources {
        cpu    = 500
        memory = 1024
      }
    }
    task "egress" {
      driver = "docker"
      config {
        image        = "registry.pkubelka.cz/keeper-egress:main-af9cd22"
        force_pull   = true
        network_mode = "host"
      }

      lifecycle {
        hook    = "prestart"
        sidecar = true
      }

      env {
        WG_PRIVATE_KEY   = var.wg_private_key
        WG_ADDRESSES     = var.wg_addresses
        WG_PEER_PUBLIC_KEY = var.wg_peer_public_key
        WG_PEER_ENDPOINT   = var.wg_peer_endpoint
      }

      resources {
        cpu    = 200
        memory = 128
      }
    }
  }
}
