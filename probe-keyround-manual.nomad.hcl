# probe-keyround-manual.nomad.hcl — manual single-key pin (parameterized,
# NO periodic stanza: periodic+parameterized in one file breaks manual
# dispatch evaluation on this cluster, so the two mechanisms live apart.
# The periodic twin is probe-keyround.nomad.hcl (pool heartbeat).
#
#   nomad job dispatch -meta key=OPENCODE_ZEN_RETIRED_1 keyround-manual
#
# Values NEVER in git — keys_json rendered from Bao at register (see
# probe-keyround.nomad.hcl header). Memory floor 1024MB (proven).

variable "dr_user" {
  type    = string
  default = ""
}

variable "dr_pass" {
  type    = string
  default = ""
}

variable "keys_json" {
  type    = string
  default = "[]"
}

job "keyround-manual" {
  datacenters = ["ovh-vps"]
  type        = "batch"

  parameterized {
    payload = "optional"
    meta_required = ["key"]
  }


  group "round" {
    count = 1

    task "keyround" {
      driver = "docker"
      config {
        image      = "registry.pkubelka.cz/zencli:main-6"
        force_pull = true
        auth {
          username = var.dr_user
          password = var.dr_pass
        }
        # Override the image ENTRYPOINT (zencli serve loop); the round
        # is driven by keyround.py directly.
        entrypoint = ["python3"]
        args       = ["/srv/probe/keyround.py"]
      }

      env {
        KEYS_JSON           = var.keys_json
        KEYROUND_KEY        = "${NOMAD_META_key}"
        KEYROUND_JITTER_SECS = "600"
      }

      resources {
        cpu    = 500
        memory = 1024
      }
    }
  }
}
