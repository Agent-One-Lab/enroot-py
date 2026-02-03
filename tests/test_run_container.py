

from enroot import from_env

client = from_env()

image = client.images.pull("alpine", "latest", registry_host="docker.io")
ref = image.tags[0]
cont = client.containers.run(ref, name=None, detach=True)
print(cont.exec_run("echo hello"))