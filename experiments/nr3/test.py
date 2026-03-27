start_all()

# machine = nodes.machine

machine.succeed("ls /run/current-system/sw/bin/binary")

result = machine.succeed("ls -l /run/current-system/sw/bin/binary")
machine.log(result)

# machine.shell_interact()

result = machine.succeed("/run/current-system/sw/bin/binary")
print(result)

result = machine.succeed("time /run/current-system/sw/bin/binary")
print(result)

result = machine.succeed("/run/current-system/sw/bin/binary")
print(result)

