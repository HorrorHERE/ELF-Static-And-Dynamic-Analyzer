import os

def dumpCallGraph():
    functionManager = currentProgram.getFunctionManager()
    
    G = '''digraph "Program Call Graph" {
  rankdir=TB;
  node [shape=box, style=filled, fillcolor=lightblue, fontname="monospace"];
  edge [color=gray];
  
'''
    
    added_funcs = set()
    
    for func in functionManager.getFunctions(True):
        if func.isExternal():
            continue
        
        func_name = func.getName()
        func_addr = func.getEntryPoint().getOffset()
        node_id = "func_%x" % func_addr
        
        if func_addr not in added_funcs:
            label = func_name.replace('"', '\\"')
            G += '  %s [label="%s\\n(0x%x)"];\n' % (node_id, label, func_addr)
            added_funcs.add(func_addr)
        
        called_functions = func.getCalledFunctions(monitor)
        
        for called_func in called_functions:
            if called_func.isExternal():
                continue
            
            called_addr = called_func.getEntryPoint().getOffset()
            called_node_id = "func_%x" % called_addr
            
            if called_addr not in added_funcs:
                called_label = called_func.getName().replace('"', '\\"')
                G += '  %s [label="%s\\n(0x%x)"];\n' % (called_node_id, called_label, called_addr)
                added_funcs.add(called_addr)
            
            G += '  %s -> %s;\n' % (node_id, called_node_id)
    
    G += '}\n'
    
    prog_name = currentProgram.getName()
    safe_name = "".join([c for c in prog_name if c.isalnum() or c in ('_', '-', '.')])
    
    output_path = '/tmp/cfg/call_graph_%s.dot' % safe_name
    
    with open(output_path, 'w') as dot_output:
        dot_output.write(G)
    
    print("SUCCESS: CFG saved to: %s" % output_path)

if __name__ == "__main__":
    dumpCallGraph()
