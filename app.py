import os
import logging
import socket
import subprocess
import time
from typing import Optional

import paramiko
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="SSH Node Checker")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("ssh-node-checker")


class CheckNodeRequest(BaseModel):
    ip: str = Field(..., min_length=7)
    command: str = Field(default="echo ok")
    timeoutSeconds: int = Field(default=5, ge=1, le=15)
    port: int = Field(default=22, ge=1, le=65535)


class CheckSftpRequest(BaseModel):
    ip: str = Field(..., min_length=7)
    remotePath: str = Field(default=".", min_length=1)
    timeoutSeconds: int = Field(default=5, ge=1, le=15)
    port: int = Field(default=22, ge=1, le=65535)


class CheckConnectivityRequest(BaseModel):
    ip: str = Field(..., min_length=7)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    timeoutSeconds: int = Field(default=5, ge=1, le=15)
    attempts: int = Field(default=1, ge=1, le=100)
    intervalSeconds: int = Field(default=10, ge=0, le=3600)


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


def connect_sftp(
    ip: str, user: str, password: str, timeout_seconds: int, port: int = 22
) -> tuple[paramiko.Transport, paramiko.SFTPClient]:
    sock = socket.create_connection((ip, port), timeout=timeout_seconds)
    transport = paramiko.Transport(sock)
    transport.banner_timeout = timeout_seconds
    transport.auth_timeout = timeout_seconds
    transport.connect(username=user, password=password)
    return transport, paramiko.SFTPClient.from_transport(transport)


def _sftp_error_response(error_code: str, message: str, details: str = "") -> dict:
    payload = {
        "registered": True,
        "sshConnected": False,
        "sftpConnected": False,
        "operationExecuted": False,
        "entries": [],
        "errorCode": error_code,
        "errorMessage": message,
    }
    if details:
        payload["details"] = details
    return payload


def run_sftp_check(
    ip: str,
    user: str,
    password: str,
    remote_path: str,
    timeout_seconds: int,
    port: int = 22,
) -> dict:
    transport = None
    sftp = None

    try:
        transport, sftp = connect_sftp(ip, user, password, timeout_seconds, port)
        entries = [
            {
                "name": entry.filename,
                "isDirectory": entry.st_mode is not None and (entry.st_mode & 0o170000) == 0o040000,
                "size": entry.st_size,
            }
            for entry in sftp.listdir_attr(remote_path)
        ]
        return {
            "registered": True,
            "sshConnected": True,
            "sftpConnected": True,
            "operationExecuted": True,
            "remotePath": remote_path,
            "entries": entries,
            "errorCode": None,
            "errorMessage": None,
        }
    except paramiko.AuthenticationException as exc:
        return _sftp_error_response("AUTH_FAILED", "Authentication failed.", str(exc))
    except (socket.timeout, TimeoutError) as exc:
        return _sftp_error_response("TIMEOUT", "SFTP connection timed out.", str(exc))
    except socket.gaierror as exc:
        return _sftp_error_response("UNKNOWN_HOST", "Host could not be resolved.", str(exc))
    except OSError as exc:
        return _sftp_error_response("HOST_UNREACHABLE", "Host is unreachable or port closed.", str(exc))
    except paramiko.SSHException as exc:
        return _sftp_error_response("SFTP_ERROR", "SFTP operation failed.", str(exc))
    except Exception as exc:
        return _sftp_error_response("SFTP_ERROR", "Unexpected SFTP failure.", str(exc))
    finally:
        if sftp is not None:
            sftp.close()
        if transport is not None:
            transport.close()


def run_connectivity_check(ip: str, port: Optional[int], timeout_seconds: int) -> dict:
    if port is None:
        return run_icmp_ping(ip, timeout_seconds)

    started_at = time.perf_counter()

    try:
        with socket.create_connection((ip, port), timeout=timeout_seconds):
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            return {
                "registered": True,
                "reachable": True,
                "checkType": "TCP",
                "ip": ip,
                "port": port,
                "latencyMs": latency_ms,
                "errorCode": None,
                "errorMessage": None,
            }
    except (socket.timeout, TimeoutError) as exc:
        error_code = "TIMEOUT"
        error_message = "Connection timed out."
    except socket.gaierror as exc:
        error_code = "UNKNOWN_HOST"
        error_message = "Host could not be resolved."
    except OSError as exc:
        error_code = "PORT_UNREACHABLE"
        error_message = "Host is unreachable or port is closed."

    return {
        "registered": True,
        "reachable": False,
        "checkType": "TCP",
        "ip": ip,
        "port": port,
        "latencyMs": round((time.perf_counter() - started_at) * 1000, 2),
        "errorCode": error_code,
        "errorMessage": error_message,
        "details": str(exc),
    }


def run_icmp_ping(ip: str, timeout_seconds: int) -> dict:
    started_at = time.perf_counter()
    timeout_milliseconds = timeout_seconds * 1000

    if os.name == "nt":
        command = ["ping", "-n", "1", "-w", str(timeout_milliseconds), ip]
    else:
        command = ["ping", "-c", "1", "-W", str(timeout_seconds), ip]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 1,
            check=False,
        )
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        if result.returncode == 0:
            return {
                "registered": True,
                "reachable": True,
                "checkType": "ICMP",
                "ip": ip,
                "port": None,
                "latencyMs": latency_ms,
                "errorCode": None,
                "errorMessage": None,
            }

        details = (result.stderr or result.stdout).strip()
        return {
            "registered": True,
            "reachable": False,
            "checkType": "ICMP",
            "ip": ip,
            "port": None,
            "latencyMs": latency_ms,
            "errorCode": "PING_FAILED",
            "errorMessage": "The host did not respond to ICMP ping.",
            "details": details,
        }
    except FileNotFoundError as exc:
        return {
            "registered": True,
            "reachable": False,
            "checkType": "ICMP",
            "ip": ip,
            "port": None,
            "latencyMs": round((time.perf_counter() - started_at) * 1000, 2),
            "errorCode": "PING_NOT_AVAILABLE",
            "errorMessage": "The ping command is not available in the container.",
            "details": str(exc),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "registered": True,
            "reachable": False,
            "checkType": "ICMP",
            "ip": ip,
            "port": None,
            "latencyMs": round((time.perf_counter() - started_at) * 1000, 2),
            "errorCode": "TIMEOUT",
            "errorMessage": "Ping timed out.",
            "details": str(exc),
        }


def run_periodic_connectivity_check(
    ip: str,
    port: Optional[int],
    timeout_seconds: int,
    attempts: int,
    interval_seconds: int,
) -> dict:
    check_type = "ICMP" if port is None else "TCP"
    results = []

    logger.info(
        "Iniciando conectividad: destino=%s, tipo=%s, puerto=%s, intentos=%s, intervalo=%ss",
        ip,
        check_type,
        port if port is not None else "N/A",
        attempts,
        interval_seconds,
    )

    for attempt in range(1, attempts + 1):
        logger.info("Ping %s/%s iniciado para %s", attempt, attempts, ip)
        result = run_connectivity_check(ip, port, timeout_seconds)
        result["attempt"] = attempt
        results.append(result)
        logger.info(
            "Ping %s/%s resultado: reachable=%s, latencyMs=%s, errorCode=%s",
            attempt,
            attempts,
            result["reachable"],
            result["latencyMs"],
            result["errorCode"],
        )

        if attempt < attempts:
            logger.info(
                "Esperando %s segundos para el siguiente ping",
                interval_seconds,
            )
            time.sleep(interval_seconds)

    successful_attempts = sum(1 for result in results if result["reachable"])
    logger.info(
        "Conectividad finalizada para %s: exitosos=%s, fallidos=%s",
        ip,
        successful_attempts,
        attempts - successful_attempts,
    )

    return {
        "registered": True,
        "ip": ip,
        "checkType": check_type,
        "port": port,
        "attempts": attempts,
        "successfulAttempts": successful_attempts,
        "failedAttempts": attempts - successful_attempts,
        "results": results,
    }


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


@app.post("/check-sftp")
def check_sftp(payload: CheckSftpRequest):
    node = find_node(payload.ip)
    if not node:
        return {
            "registered": False,
            "sshConnected": False,
            "sftpConnected": False,
            "operationExecuted": False,
            "entries": [],
            "errorCode": "NODE_NOT_FOUND",
            "errorMessage": "The IP is not registered in the node list.",
        }

    return run_sftp_check(
        ip=payload.ip,
        user=node["user"],
        password=node["password"],
        remote_path=payload.remotePath,
        timeout_seconds=payload.timeoutSeconds,
        port=payload.port,
    )


@app.post("/check-connectivity")
def check_connectivity(payload: CheckConnectivityRequest):
    node = find_node(payload.ip)
    if not node:
        logger.warning("IP no registrada para conectividad: %s", payload.ip)
        return {
            "registered": False,
            "reachable": False,
            "checkType": "ICMP" if payload.port is None else "TCP",
            "ip": payload.ip,
            "port": payload.port,
            "latencyMs": None,
            "errorCode": "NODE_NOT_FOUND",
            "errorMessage": "The IP is not registered in the node list.",
        }

    return run_periodic_connectivity_check(
        ip=payload.ip,
        port=payload.port,
        timeout_seconds=payload.timeoutSeconds,
        attempts=payload.attempts,
        interval_seconds=payload.intervalSeconds,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=False)
