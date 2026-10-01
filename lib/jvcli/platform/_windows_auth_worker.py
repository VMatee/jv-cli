"""Internal disposable auth owner. Secrets use private pipes, never stdout."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from jvcli.transport import JvApiClient, JvClientConfig
from jvcli.safety import strict_json


def main():
    import msvcrt
    fd = msvcrt.open_osfhandle(int(sys.argv[1]), os.O_WRONLY | os.O_BINARY)
    with os.fdopen(fd, 'wb', buffering=0) as output:
        try:
            raw = sys.stdin.buffer.read(65537)
            if len(raw) > 65536:
                raise ValueError()
            request = strict_json(raw)
            client = JvApiClient(JvClientConfig(base_url=request['base'],
                                               request_timeout=request['timeout']))
            if request['operation'] == 'login':
                client.login(request['username'], request['password'])
                result = {'token': client._token}
            elif request['operation'] == 'logout':
                client._token = request['token']
                client.logout()
                result = {'ok': True}
            else:
                raise ValueError()
            data = json.dumps(result, ensure_ascii=True).encode()
            while data:
                count = output.write(data)
                if not count:
                    raise OSError()
                data = data[count:]
        except Exception:
            # No exception/request/response text may reach diagnostics.
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
