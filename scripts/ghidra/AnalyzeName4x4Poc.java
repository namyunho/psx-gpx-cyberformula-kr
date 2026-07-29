// Ghidra headless cross-check for the Disc 1 4+4 player-name PoC.
// @category CyberFormula

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;

public class AnalyzeName4x4Poc extends GhidraScript {
    private Address address(String value) {
        return toAddr(Long.parseUnsignedLong(value, 16));
    }

    private void requireWord(String value, long expected) throws Exception {
        long actual = Integer.toUnsignedLong(getInt(address(value)));
        if (actual != expected) {
            throw new IllegalStateException(
                value + " word " + Long.toHexString(actual) +
                " != " + Long.toHexString(expected));
        }
        println("WORD " + value + " " + Long.toHexString(actual));
    }

    private void requireHalfword(String value, int expected) throws Exception {
        int actual = Short.toUnsignedInt(getShort(address(value)));
        if (actual != expected) {
            throw new IllegalStateException(
                value + " halfword " + Integer.toHexString(actual) +
                " != " + Integer.toHexString(expected));
        }
        println("HALFWORD " + value + " " + Integer.toHexString(actual));
    }

    private void printReferences(String value) {
        Address target = address(value);
        println("REFERENCES " + value);
        ReferenceIterator references =
            currentProgram.getReferenceManager().getReferencesTo(target);
        while (references.hasNext()) {
            Reference reference = references.next();
            println("  " + reference.getFromAddress() + " " +
                reference.getReferenceType());
        }
    }

    private void printInstructions(String startValue, String endValue) {
        Address start = address(startValue);
        Address end = address(endValue);
        println("INSTRUCTIONS " + startValue + ".." + endValue);
        for (Instruction instruction :
                currentProgram.getListing().getInstructions(
                    new AddressSet(start, end), true)) {
            println("  " + instruction.getAddress() + "  " +
                instruction.toString());
        }
    }

    private void decompileContaining(String value) {
        Address target = address(value);
        Function function =
            currentProgram.getFunctionManager().getFunctionContaining(target);
        if (function == null) {
            println("DECOMPILE " + value + " no function");
            return;
        }
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        DecompileResults results = decompiler.decompileFunction(
            function, 60, monitor);
        println("DECOMPILE " + value + " " + function.getName());
        if (!results.decompileCompleted()) {
            println("  ERROR " + results.getErrorMessage());
            decompiler.dispose();
            return;
        }
        println(results.getDecompiledFunction().getC());
        decompiler.dispose();
    }

    private void analyzeUnit35() throws Exception {
        requireWord("80087814", 0x801f07b0L);
        requireWord("80087818", 0x801f0eb0L);
        requireWord("8008781c", 0x801f15b0L);
        requireWord("80087820", 0x801f1cb0L);
        printInstructions("8006e07c", "8006e0dc");
        decompileContaining("8006e0b8");
    }

    private void analyzeUnit39() {
        printReferences("8002afdc");
        printReferences("8002b22c");
        printReferences("8002b47c");
        printReferences("8002b6cc");
        printReferences("801f07b0");
        printReferences("801f0eb0");
        printReferences("801f15b0");
        printReferences("801f1cb0");
        printInstructions("80098dfc", "80098e68");
        printInstructions("800991a0", "800992a4");
        printInstructions("8009a690", "8009a74c");
        printInstructions("8009a9a4", "8009a9f0");
        decompileContaining("800991a0");
        decompileContaining("8009a9a4");
    }

    private void analyzeUnit40() {
        printReferences("8002ad8c");
        printReferences("8002aeb4");
        printReferences("8002aefe");
        printInstructions("800993bc", "8009964c");
        printInstructions("8009974c", "80099b50");
        printInstructions("8009ab40", "8009ad74");
        printInstructions("8009ae00", "8009af84");
        decompileContaining("8009942c");
    }

    private void analyzeSlps() throws Exception {
        for (int index = 0; index < 8; index++) {
            long address = 0x8004f35cL + index * 2L;
            requireHalfword(
                Long.toHexString(address),
                0x4ce + index);
        }
        printReferences("8004f35c");
        printReferences("8004f364");
        printReferences("80061580");
        printReferences("800615f8");
        printInstructions("80039ed0", "80039f58");
        printInstructions("8003a6b0", "8003a6f4");
        printInstructions("8003a8e0", "8003a940");
        printInstructions("8003d5dc", "8003d664");
        printInstructions("8003da2c", "8003dab4");
        printInstructions("8003e96c", "8003e9a8");
        decompileContaining("80039ed0");
        decompileContaining("8003a6b0");
        decompileContaining("8003d5dc");
    }

    @Override
    protected void run() throws Exception {
        String name = currentProgram.getName();
        println("PROGRAM " + name);
        if (name.contains("unit35")) {
            analyzeUnit35();
            return;
        }
        if (name.contains("unit39")) {
            analyzeUnit39();
            return;
        }
        if (name.contains("unit40")) {
            analyzeUnit40();
            return;
        }
        if (name.contains("SLPS_019.58")) {
            analyzeSlps();
        }
    }
}
