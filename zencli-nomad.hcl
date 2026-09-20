# zencli-nomad.hcl — one-shot batch validation: zencli serves on Nomad,
# answers one echo prompt, alloc log is the receipt.
#
# Build + push (from repo root):
#   GOOS=linux GOARCH=amd64 go build -o zencli/zencli-linux ./zencli/
#   docker build -f zencli/Dockerfile -t registry.pkubelka.cz/zencli:main-1 .
#   docker push registry.pkubelka.cz/zencli:main-1
#
# Register (tokens NEVER in git — pass via -var):
#   export NOMAD_ADDR=https://nomad.pkubelka.cz  # or loopback :4647
#   export NOMAD_TOKEN=$(bao kv get -field=management secret/projects/NomadSetup/acl)
#   nomad job run \
#     -var=dr_user="publisher" \
#     -var=dr_pass="$(...registry password...)" \
#     -var=opencode_auth_json="$(cat ~/.local/share/opencode/auth.json)" \
#     zencli-nomad.hcl
# Batch runs once on register; watch the alloc, expect NOMAD-ZENCLI-ALIVE.
#
# Secrets NEVER in git — both -vars flow shell→Nomad only.
# Memory floor 1024MB: the opencode CLI SIGKILLs at 256MB (proven).

variable "dr_user" {
  type    = string
  default = ""
}

variable "dr_pass" {
  type    = string
  default = ""
}

variable "opencode_auth_json" {
  type    = string
  default = "{}"
}

job "zencli-validate" {
  datacenters = ["ovh-vps"]
  type        = "batch"

  group "validate" {
    count = 1

    task "zencli" {
      driver = "docker"
      config {
        image      = "registry.pkubelka.cz/zencli:main-1"
        force_pull = true
        auth {
          username = var.dr_user
          password = var.dr_pass
        }
      }

      env {
        OPENCODE_AUTH_FILE = "${NOMAD_SECRETS_DIR}/opencode-auth.json"
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
  }
}
