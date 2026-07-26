// Ghidra headless cross-check for the Disc 1 character-name consumers.
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

public class AnalyzeCharacterNames extends GhidraScript {
    private Address address(String value) {
        return toAddr(Long.parseUnsignedLong(value, 16));
    }

    private void printReferences(String value) {
        Address target = address(value);
        println("REFERENCES " + value);
        ReferenceIterator references = currentProgram.getReferenceManager()
            .getReferencesTo(target);
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

    private void decompile(String value) {
        Address target = address(value);
        Function function = currentProgram.getFunctionManager()
            .getFunctionContaining(target);
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

    @Override
    protected void run() throws Exception {
        String name = currentProgram.getName();
        println("PROGRAM " + name);
        if (name.contains("ALLBIN-unit40")) {
            printReferences("8002ad8c");
            printReferences("8002ae6a");
            printReferences("800a0714");
            printReferences("800a071c");
            printInstructions("800993bc", "8009964c");
            printInstructions("8009974c", "80099b50");
            printInstructions("8009ab40", "8009ad74");
            printInstructions("8009ae00", "8009af84");
            return;
        }
        if (name.contains("SLPS_019.58")) {
            printReferences("8004f36c");
            printReferences("80061164");
            printReferences("80061180");
            printReferences("80061580");
            printReferences("800615f8");
            printInstructions("80039ed0", "80039f28");
            printInstructions("8003a6a8", "8003a948");
            decompile("80032704");
            decompile("800329b8");
            decompile("80039d24");
            decompile("8003a434");
            decompile("8003e760");
        }
    }
}
