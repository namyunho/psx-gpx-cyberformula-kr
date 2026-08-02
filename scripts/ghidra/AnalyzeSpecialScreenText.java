// Ghidra headless cross-check for mini-game, course, and machine-setting text.
// @category CyberFormula

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;

public class AnalyzeSpecialScreenText extends GhidraScript {
    private Address address(String value) {
        return toAddr(Long.parseUnsignedLong(value, 16));
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

    private void printCodeReferencesInto(
            String startValue,
            String endValue,
            String codeEndValue) {
        Address target = address(startValue);
        Address end = address(endValue);
        Address codeEnd = address(codeEndValue);
        println("CODE_REFERENCES_INTO " + startValue + ".." + endValue);
        while (target.compareTo(end) <= 0) {
            ReferenceIterator references =
                currentProgram.getReferenceManager().getReferencesTo(target);
            while (references.hasNext()) {
                Reference reference = references.next();
                if (reference.getFromAddress().compareTo(codeEnd) < 0) {
                    println("  " + target + " <- " +
                        reference.getFromAddress() + " " +
                        reference.getReferenceType());
                }
            }
            target = target.add(2);
        }
    }

    private void decompile(String value) {
        Address target = address(value);
        Function function =
            currentProgram.getFunctionManager().getFunctionContaining(target);
        if (function == null) {
            disassemble(target);
            function = createFunction(target, null);
        }
        if (function == null) {
            println("DECOMPILE " + value + " no function after disassembly");
            return;
        }
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        DecompileResults results =
            decompiler.decompileFunction(function, 60, monitor);
        println("DECOMPILE " + value + " " + function.getName());
        if (!results.decompileCompleted()) {
            println("  ERROR " + results.getErrorMessage());
            decompiler.dispose();
            return;
        }
        println(results.getDecompiledFunction().getC());
        decompiler.dispose();
    }

    private void analyzeMiniGameOverlay() {
        printCodeReferencesInto("800b0000", "800b6d7a", "800b0000");
        printReferences("800b033c");
        printReferences("800b0508");
        printReferences("800b0768");
        printReferences("800b0b98");
        printReferences("800b58e4");
        printReferences("800b5940");
        decompile("800a734c");
        decompile("800a7470");
        decompile("800a7ad0");
        decompile("800a7cfc");
        decompile("800a76ac");
        // Cooking-result text is assembled from a fixed dialogue prefix plus
        // one of two code-referenced word tables.  Keep these consumer paths
        // in the same reproducible cross-check as the direct renderer calls.
        decompile("8009a674");
        decompile("8009a834");
    }

    private void analyzeCourseAndMachineOverlay() {
        // These two ranges are consumed as sequential control streams around
        // the directly addressed setting descriptions.  An empty direct-xref
        // result is expected and is useful evidence against inventing a
        // pointer table; control adjacency and runtime routing remain the
        // adoption boundary.
        printCodeReferencesInto("800abea8", "800ac066", "800abea8");
        printCodeReferencesInto("800ac444", "800ac782", "800ac444");
        printReferences("800ad46c");
        printReferences("800aad40");
        printReferences("800ac068");
        printReferences("800ac0c8");
        printReferences("800ac120");
        printReferences("800ac17c");
        printReferences("800ac208");
        printReferences("800ac320");
        decompile("800a9788");
        decompile("800a816c");
    }

    @Override
    protected void run() throws Exception {
        String name = currentProgram.getName();
        println("PROGRAM " + name);
        if (name.contains("unit-0038")) {
            analyzeMiniGameOverlay();
        }
        else if (name.contains("unit-0043")) {
            analyzeCourseAndMachineOverlay();
        }
    }
}
