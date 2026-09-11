import os
import socket
from typing import Optional

import paramiko
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="SSH Node Checker")


class CheckNodeRequest(BaseModel):
    ip: str = Field(..., min_length=7)
    command: str = Field(default="echo ok")
    timeoutSeconds: int = Field(default=5, ge=1, le=15)
    port: int = Field(default=22, ge=1, le=65535)


def load_nodes() -> list[dict]:
    file_path = os.environ.get("NODE_FILE", os.path.join(os.path.dirname(__file__), "nodes.txt"))
    nodes: list[dict] = []

    if not os.path.exists(file_path):
        return nodes

    with open(file_path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) < 3:
                continue
            ip, user, password = parts[0], parts[1], parts[2]
            nodes.append({"ip": ip, "user": user, "password": password})

    return nodes


def find_node(ip: str) -> Optional[dict]:
    for node in load_nodes():
        if node["ip"] == ip:
            return node
    return None


def _ssh_error_response(error_code: str, message: str, details: str = "") -> dict:
    payload = {
        "registered": True,
        "sshConnected": False,
        "commandExecuted": False,
        "timedOut": False,
        "errorCode": error_code,
        "errorMessage": message,
        "stdout": "",
        "stderr": "",
    }
    if details:
        payload["details"] = details
    return payload


def run_remote_check(ip: str, user: str, password: str, command: str, timeout_seconds: int, port: int = 22) -> dict:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            hostname=ip,
            username=user,
            password=password,
            port=port,
            timeout=10,
            banner_timeout=10,
            auth_timeout=10,
        )
    except paramiko.AuthenticationException as exc:
        return _ssh_error_response("AUTH_FAILED", "Authentication failed.", str(exc))
    except socket.timeout as exc:
        return _ssh_error_response("TIMEOUT", "Connection timed out.", str(exc))
    except socket.gaierror as exc:
        return _ssh_error_response("UNKNOWN_HOST", "Host could not be resolved.", str(exc))
    except OSError as exc:
        return _ssh_error_response("HOST_UNREACHABLE", "Host is unreachable or port closed.", str(exc))
    except paramiko.SSHException as exc:
        return _ssh_error_response("SSH_PROTOCOL_ERROR", "SSH protocol error.", str(exc))
    except Exception as exc:
        return _ssh_error_response("SSH_ERROR", "Unexpected SSH failure.", str(exc))

    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds)
        stdout_text = stdout.read().decode("utf-8", errors="replace")
        stderr_text = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()

        return {
            "registered": True,
            "sshConnected": True,
            "commandExecuted": True,
            "timedOut": False,
            "exitCode": exit_code,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "errorCode": None,
            "errorMessage": None,
        }
    except socket.timeout as exc:
        return {
            "registered": True,
            "sshConnected": True,
            "commandExecuted": False,
            "timedOut": True,
            "exitCode": None,
            "stdout": "",
            "stderr": "",
            "errorCode": "COMMAND_TIMEOUT",
            "errorMessage": f"Command exceeded the allowed timeout of {timeout_seconds} seconds.",
            "details": str(exc),
        }
    except Exception as exc:
        return {
            "registered": True,
            "sshConnected": True,
            "commandExecuted": False,
            "timedOut": False,
            "exitCode": None,
            "stdout": "",
            "stderr": "",
            "errorCode": "COMMAND_ERROR",
            "errorMessage": "The command could not be executed.",
            "details": str(exc),
        }
    finally:
        client.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/check-node")
def check_node(payload: CheckNodeRequest):
    node = find_node(payload.ip)
    if not node:
        return {
            "registered": False,
            "sshConnected": False,
            "commandExecuted": False,
            "timedOut": False,
            "errorCode": "NODE_NOT_FOUND",
            "errorMessage": "The IP is not registered in the node list.",
            "stdout": "",
            "stderr": "",
        }

    return run_remote_check(
        ip=payload.ip,
        user=node["user"],
        password=node["password"],
        command=payload.command,
        timeout_seconds=payload.timeoutSeconds,
        port=payload.port,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=False)
