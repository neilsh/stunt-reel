// Creates a function at every .SOD display-list handler and names it from
// research/formats/sod-opcodes.md.
//
// The VM dispatches an opcode through a 9-byte slot: "mov word es:[si-2], imm16" then an
// "E9 rel16" jump, with the handler at imm16 plus the slot run's image offset
// (research/playone-exe/sod-vm.md section 1). The run, its image offset and its length are read
// from the loaded program, so neither the offset (0x8240 unpatched, 0x7540 Patch #3) nor the
// count (108 unpatched, 107 Patch #3) is assumed here.
//
// Usage, as the mise task runs it:
//   analyzeHeadless <project_location> <project_name> -import <mz>
//       -scriptPath tools/ghidra -postScript SodDispatchTable.java <slots.tsv>
// The slot file is written by python/scripts/ghidra_sod_dispatch.py. Headless saves the imported
// program and the new functions when the session ends, unless -readOnly or -deleteProject is
// passed.
//
// research/playone-exe/static-tooling.md section 5.

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.MemoryAccessException;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.SourceType;
import ghidra.util.exception.DuplicateNameException;
import ghidra.util.exception.InvalidInputException;

public class SodDispatchTable extends GhidraScript {
    private static final byte[] SLOT_PREFIX = { 0x26, (byte) 0xC7, 0x44, (byte) 0xFE };
    private static final int SLOT_BYTES = 9;
    private static final int MIN_SLOTS = 100;
    private static final int NUMBERING_START = 0x0333;
    private static final long MAX_BLOCK = 64L * 1024 * 1024;

    private static final class Entry {
        private final int index;
        private final int opcode;
        private final int handler;
        private final String name;

        private Entry(int index, int opcode, int handler, String name) {
            this.index = index;
            this.opcode = opcode;
            this.handler = handler;
            this.name = name;
        }
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            String message = "SodDispatchTable: usage: SodDispatchTable.java <slots.tsv>";
            printerr(message);
            throw new IllegalArgumentException(message);
        }
        String build = "";
        int tableImage = -1;
        int declared = -1;
        List<Entry> entries = new ArrayList<>();
        for (String line : Files.readAllLines(Path.of(args[0]), StandardCharsets.UTF_8)) {
            if (line.startsWith("#")) {
                for (String part : line.substring(1).trim().split("\\s+")) {
                    int equals = part.indexOf('=');
                    if (equals < 0) {
                        continue;
                    }
                    String key = part.substring(0, equals);
                    String value = part.substring(equals + 1);
                    if (key.equals("build")) {
                        build = value;
                    } else if (key.equals("table")) {
                        tableImage = Integer.decode(value);
                    } else if (key.equals("slots")) {
                        declared = Integer.decode(value);
                    }
                }
                continue;
            }
            if (line.isBlank()) {
                continue;
            }
            String[] fields = line.split("\t", -1);
            if (fields.length < 4) {
                throw new IOException("SodDispatchTable: bad slot line: " + line);
            }
            entries.add(new Entry(
                Integer.parseInt(fields[0]),
                Integer.decode(fields[1]),
                Integer.decode(fields[2]),
                fields[3].trim()));
        }
        if (tableImage < 0 || declared < 0) {
            throw new IOException("SodDispatchTable: the slot file lacks table= or slots=");
        }
        if (entries.size() != declared) {
            throw new IOException("SodDispatchTable: " + entries.size()
                + " slot lines but the header says " + declared);
        }
        Address table = findSlotTable();
        int found = slotRun(table);
        if (found != declared) {
            throw new IOException("SodDispatchTable: the program's run has " + found
                + " slots, the slot file says " + declared);
        }
        Address imageBase = imageBase();
        long foundTableImage = table.subtract(imageBase);
        if (foundTableImage != tableImage) {
            throw new IOException("SodDispatchTable: the slot run is at image 0x"
                + Long.toHexString(foundTableImage) + ", the slot file says image 0x"
                + Integer.toHexString(tableImage));
        }
        int named = 0;
        int unnamed = 0;
        int failed = 0;
        for (Entry entry : entries) {
            Address slot = table.add((long) entry.index * SLOT_BYTES);
            byte[] bytes = new byte[SLOT_BYTES];
            try {
                currentProgram.getMemory().getBytes(slot, bytes);
            } catch (MemoryAccessException e) {
                throw new IOException("SodDispatchTable: cannot read slot " + entry.index
                    + " at " + slot, e);
            }
            if (!isSlot(bytes, 0)) {
                throw new IOException("SodDispatchTable: slot " + entry.index + " at " + slot
                    + " is not a dispatch slot");
            }
            int imm16 = (bytes[4] & 0xFF) | ((bytes[5] & 0xFF) << 8);
            // The handler is an offset in the slot run's CODE_1 segment, so table.add(imm16) is
            // the address; imageBase.add(entry.handler) must agree (static-tooling.md section 3).
            Address handler = table.add(imm16);
            Address fromImage = imageBase.add(entry.handler);
            if (!handler.equals(fromImage)) {
                throw new IOException("SodDispatchTable: slot " + entry.index + " names handler "
                    + fromImage + " from its image offset but " + handler + " from its segment");
            }
            DisassembleCommand disassemble = new DisassembleCommand(handler, null, true);
            boolean changed = disassemble.applyTo(currentProgram, monitor);
            if (currentProgram.getListing().getInstructionAt(handler) == null) {
                throw new IOException("SodDispatchTable: no instruction at handler " + handler
                    + " after disassembling (changed=" + changed + ")");
            }
            Function function = currentProgram.getFunctionManager().getFunctionAt(handler);
            if (function == null) {
                CreateFunctionCmd command = new CreateFunctionCmd(handler);
                if (!command.applyTo(currentProgram, monitor)) {
                    printerr("SodDispatchTable: could not create a function at " + handler
                        + " (slot " + entry.index + ")");
                    failed++;
                    continue;
                }
                function = currentProgram.getFunctionManager().getFunctionAt(handler);
            }
            if (function == null) {
                printerr("SodDispatchTable: no function at " + handler + " after creating one");
                failed++;
                continue;
            }
            if (!entry.name.isEmpty()) {
                try {
                    function.setName(entry.name, SourceType.USER_DEFINED);
                } catch (DuplicateNameException | InvalidInputException e) {
                    printerr("SodDispatchTable: cannot name " + handler + " " + entry.name + ": "
                        + e.getMessage());
                    failed++;
                    continue;
                }
                named++;
            } else {
                unnamed++;
            }
            function.setComment(comment(entry, build));
        }
        if (failed > 0) {
            throw new IOException("SodDispatchTable: " + failed + " of " + entries.size()
                + " handlers failed");
        }
        println("ghidra-sod-table: OK - " + (named + unnamed) + " functions from "
            + entries.size() + " slots (" + named + " named, " + unnamed + " unnamed); table at "
            + table + " (image 0x" + Integer.toHexString(tableImage) + "), " + build + " build");
    }

    private String comment(Entry entry, String build) {
        StringBuilder text = new StringBuilder(String.format(
            "SOD display-list handler for opcode 0x%04X (dispatch slot %d), at image 0x%04X"
                + " in the %s build.",
            entry.opcode, entry.index, entry.handler, build.isEmpty() ? "custom" : build));
        if (entry.name.isEmpty()) {
            text.append(String.format("%nNo name: the opcode is past the table's rows."));
        } else {
            text.append(String.format(
                "%nNamed %s from research/formats/sod-opcodes.md by slot index.", entry.name));
        }
        if (entry.opcode > NUMBERING_START) {
            text.append(String.format(
                "%nAbove opcode 0x%04X the two builds dispatch different handlers from one opcode"
                    + " word; which build's numbering the table follows is open"
                    + " (research/playone-exe/patch3.md section 4.1, issue #480).",
                NUMBERING_START));
        }
        return text.toString();
    }

    private static boolean isSlot(byte[] data, int at) {
        if (at + SLOT_BYTES > data.length) {
            return false;
        }
        for (int i = 0; i < SLOT_PREFIX.length; i++) {
            if (data[at + i] != SLOT_PREFIX[i]) {
                return false;
            }
        }
        return data[at + 6] == (byte) 0xE9;
    }

    private int slotRun(Address table) {
        int count = 0;
        byte[] bytes = new byte[SLOT_BYTES];
        while (true) {
            Address at = table.add((long) count * SLOT_BYTES);
            try {
                currentProgram.getMemory().getBytes(at, bytes);
            } catch (MemoryAccessException e) {
                return count;
            }
            if (!isSlot(bytes, 0)) {
                return count;
            }
            count++;
        }
    }

    private Address findSlotTable() throws IOException, MemoryAccessException {
        Address found = null;
        for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
            if (!block.isInitialized() || block.getSize() > MAX_BLOCK) {
                continue;
            }
            byte[] data = new byte[(int) block.getSize()];
            block.getBytes(block.getStart(), data);
            for (int at = 0; at + MIN_SLOTS * SLOT_BYTES <= data.length; at++) {
                if (!isSlot(data, at)) {
                    continue;
                }
                int run = slotRun(data, at);
                if (run < MIN_SLOTS) {
                    continue;
                }
                Address candidate = block.getStart().add(at);
                if (found != null && !found.equals(candidate)) {
                    throw new IOException("SodDispatchTable: two dispatch-slot runs, at " + found
                        + " and " + candidate);
                }
                found = candidate;
                at += run * SLOT_BYTES - 1;
            }
        }
        if (found == null) {
            throw new IOException("SodDispatchTable: no run of " + MIN_SLOTS
                + " 9-byte dispatch slots in the program");
        }
        return found;
    }

    private Address imageBase() throws IOException {
        AddressSpace space = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Address base = null;
        for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
            Address start = block.getStart();
            if (!start.getAddressSpace().equals(space)) {
                continue;
            }
            if (base == null || start.compareTo(base) < 0) {
                base = start;
            }
        }
        if (base == null) {
            throw new IOException("SodDispatchTable: the program has no default-space memory block");
        }
        return base;
    }

    private static int slotRun(byte[] data, int table) {
        int count = 0;
        while (isSlot(data, table + count * SLOT_BYTES)) {
            count++;
        }
        return count;
    }
}
