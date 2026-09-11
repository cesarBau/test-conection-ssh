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
