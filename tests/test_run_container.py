

from enroot import from_env
from time import sleep

client = from_env()

# image = client.images.pull("alpine", "latest", registry_host="docker.io")
# ref = image.tags[0]

ref = "ubuntu:20.04"
cont = client.containers.run(ref, name=None, detach=True)
print(cont.exec_run("echo hello"))