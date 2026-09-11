# SSH Node Checker

Servicio simple para validar si una IP registrada puede conectarse por SSH y ejecutar un comando con un tiempo máximo de espera.

## Formato del archivo de nodos

`nodes.txt` usa este formato:

```txt
IP|usuario|password
```

Ejemplo:

```txt
10.0.0.10|core|P@ssw0rd
10.0.0.11|root|Secret123
```

## Ejecutar

```bash
pip install -r requirements.txt
python app.py
```

## Endpoint

`POST /check-node`

Ejemplo:

```bash
curl -X POST "http://localhost:8080/check-node" \
  -H "Content-Type: application/json" \
  -d '{
    "ip": "10.0.0.10",
    "command": "echo ok",
    "timeoutSeconds": 5
  }'
```

## Respuesta de ejemplo

```json
{
  "registered": true,
  "sshConnected": true,
  "commandExecuted": true,
  "timedOut": false,
  "exitCode": 0,
  "stdout": "ok\n",
  "stderr": "",
  "errorCode": null,
  "errorMessage": null
}
```

Si falla la conexión SSH, la respuesta incluye el motivo:

```json
{
  "registered": true,
  "sshConnected": false,
  "commandExecuted": false,
  "timedOut": false,
  "errorCode": "AUTH_FAILED",
  "errorMessage": "Authentication failed.",
  "details": "Permission denied (publickey,password)"
}
```

## Endpoint SFTP

`POST /check-sftp` valida una conexión SFTP y lista el contenido de una ruta remota.

Ejemplo:

```bash
curl -X POST "http://localhost:8080/check-sftp" \
  -H "Content-Type: application/json" \
  -d '{
    "ip": "10.0.0.10",
    "remotePath": "/tmp",
    "timeoutSeconds": 5,
    "port": 22
  }'
```

La conexión SFTP usa una función independiente de la ejecución de comandos SSH y devuelve el estado de conexión y el resultado de la operación por separado.

## Endpoint de conectividad

`POST /check-connectivity` prueba la conectividad desde el servicio. Si no se envía `port`, hace un ping ICMP a la IP o dominio. Si se envía `port`, prueba conectividad TCP contra ese puerto.

El flujo permite ejecutar varios intentos. `attempts` indica cuántas veces se realiza la prueba e `intervalSeconds` indica cuántos segundos se esperan entre intentos. Por defecto se realiza un intento y el intervalo es de 10 segundos.

Ejemplo:

```bash
curl -X POST "http://localhost:8080/check-connectivity" \
  -H "Content-Type: application/json" \
  -d '{
    "ip": "servidor.midominio.com",
    "timeoutSeconds": 5,
    "attempts": 5,
    "intervalSeconds": 10
  }'
```

Para probar un servicio TCP concreto, se puede indicar el puerto:

```json
{
  "ip": "10.0.0.10",
  "port": 2222,
  "timeoutSeconds": 5
}
```

### Respuesta

```json
{
  "registered": true,
  "ip": "servidor.midominio.com",
  "checkType": "ICMP",
  "port": null,
  "attempts": 5,
  "successfulAttempts": 4,
  "failedAttempts": 1,
  "results": [
    {
      "registered": true,
      "reachable": true,
      "checkType": "ICMP",
      "ip": "servidor.midominio.com",
      "port": null,
      "latencyMs": 42.15,
      "errorCode": null,
      "errorMessage": null,
      "attempt": 1
    }
  ]
}
```

Cada intento se registra en el log del contenedor. En OpenShift se puede consultar con:

```bash
oc logs <nombre-del-pod>
```
La URL de Swagger es:
```
http://localhost:8080/docs
```

