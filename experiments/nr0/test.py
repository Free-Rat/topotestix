import time

machine2.start
machine2.succeed("ls /run/current-system/sw/bin/binary")

machine.start
machine.succeed("ls /run/current-system/sw/bin/binary")
# result = machine.succeed("time /run/current-system/sw/bin/binary &2>1")
# print(result)
# machine.succeed(f"echo '{result}' > /tmp/output")

start = time.time()       # wall-clock time
result = machine.succeed("/run/current-system/sw/bin/binary")
end = time.time()
print(f"Elapsed: {end - start} seconds")

machine.succeed(f"echo 'Elapsed: {end - start} seconds' > /tmp/output")
machine.succeed(f"echo '{result}' >> /tmp/output")

machine.copy_from_vm("/tmp/output", "output")
