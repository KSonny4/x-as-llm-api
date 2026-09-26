# probe-keyround.nomad.hcl — pool heartbeat: periodic hourly, one pool
# key + jitter per firing, never a sweep. (Manual pins live in
# probe-keyround-manual.nomad.hcl — periodic+parameterized in one file
# breaks manual dispatch evaluation on this cluster.)
#
# Pool + values via -var (values NEVER in git — rendered from Bao):
#   export NOMAD_ADDR=https://nomad.pkubelka.cz  # or loopback :4647
#   export NOMAD_TOKEN=$(bao kv get -field=management secret/projects/NomadSetup/acl)
#   KEYS_JSON="$(bash scripts/render-keyround-keys.sh)"
#   nomad job run \
#     -var=keys_json="$KEYS_JSON" \
#     probe-keyround.nomad.hcl
# Note: registry auth is client-level on the node (KSonny4/platform
# config/nomad.hcl, docker plugin auth config); specs must not carry auth.
#   nomad job dispatch -meta key=OPENCODE_ZEN_RETIRED_1 keyround  # manual pin
#
# Pool curation (enter on pass, backoff on fail, recovery events) reads
# verdict history in the keeper publish layer (M3) — the task stays
# stateless. Memory floor 1024MB (CLI SIGKILLs below it, proven).
# Auth guard: keyround.py exits 2 on missing/empty/{} values (fail closed).

variable "keys_json" {
  type    = string
  default = "[]"
}

variable "keeper_token" {
  type    = string
  default = ""
}

job "keyround-periodic" {
  datacenters = ["ovh-vps"]
  type        = "batch"

  periodic {
    cron             = "0 * * * *"
    prohibit_overlap = true
  }

  group "round" {
    count = 1

    task "keyround" {
      driver = "docker"
      config {
        image      = "registry.pkubelka.cz/zencli:main-11"
        force_pull = true
        # Override the image ENTRYPOINT (zencli serve loop); the round
        # is driven by keyround.py directly.
        entrypoint = ["python3"]
        args       = ["/srv/probe/keyround.py"]
      }

      env {
        KEYS_JSON            = var.keys_json
        KEYROUND_KEEPER_TOKEN = var.keeper_token
        KEYROUND_JITTER_SECS = "600"
      }

      resources {
        cpu    = 500
        memory = 1024
      }
    }
  }
}
