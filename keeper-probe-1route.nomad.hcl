# keeper-probe-1route.nomad.hcl — single-route paired prober (direct vs
# Mullvad-egress). Same image/auth as keeper-probe; exactly ONE zen route
# via -var seeds; proxy on/off via -var (empty = direct).
#
# Register (twice, same file — second register overwrites the first):
#   export NOMAD_ADDR=https://nomad.pkubelka.cz
#   export NOMAD_TOKEN=$(bao kv get -field=management secret/projects/NomadSetup/acl)
#   SEEDS1="$(python3 scripts/render-1route.py OPENCODE_ZEN_RETIRED_5 muse-spark-1.3-contributor-free)"
#   nomad job run \
#     -var=keeper_token="$(bao kv get -field=token secret/projects/pi-infinity-llm/KEEPER_TOKEN)" \
#     -var=seeds_json="$SEEDS1" \
#     -var=opencode_auth_json="$(cat ~/.local/share/opencode/auth.json)" \
#     -var=proxy="" \
#     keeper-probe-1route.nomad.hcl
#   nomad job dispatch keeper-probe-1route   # watch, stop after post
#   # ...then again with -var=proxy="socks5h://127.0.0.1:18080" for the
#   # Mullvad leg (needs the laptop SSH -R forward, see KEEPER_API or ask).
#
# Secrets NEVER in git — all three -vars flow shell→Nomad only.
# NO_PROXY keeps keeper POSTs on node loopback out of the proxy.

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

variable "proxy" {
  type    = string
  default = ""
}

job "keeper-probe-1route" {
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
        image        = "registry.pkubelka.cz/keeper-probe:main-act1"
        force_pull   = true
        network_mode = "host"
      }

      env {
        KEEPER_URL          = "http://127.0.0.1:8102"
        KEEPER_TOKEN        = var.keeper_token
        SEEDS_JSON          = var.seeds_json
        OPENCODE_AUTH_FILE  = "${NOMAD_SECRETS_DIR}/opencode-auth.json"
        ALL_PROXY           = var.proxy
        HTTP_PROXY          = var.proxy
        HTTPS_PROXY         = var.proxy
        NO_PROXY            = "127.0.0.1,localhost"
        no_proxy            = "127.0.0.1,localhost"
      }

      template {
        data        = var.opencode_auth_json
        destination = "${NOMAD_SECRETS_DIR}/opencode-auth.json"
        change_mode = "restart"
      }

      resources {
        cpu    = 500
        memory = 896
      }
    }
  }
}
