import ida_auto
import ida_funcs
import ida_gdl
import ida_name
import ida_pro
import idautils
import idc
import os

def main():
    try:
        if len(idc.ARGV) > 1:
            out_dir = idc.ARGV[1]
        else:
            out_dir = "."
            
        out_dir = os.path.abspath(out_dir)
        
        input_file = idc.get_input_file_path()
        base_name = os.path.basename(input_file)
        output_file = os.path.join(out_dir, base_name + ".cfg.dot")

        ida_auto.auto_wait()

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"digraph \"{base_name}\" {{\n")
            f.write("  rankdir=TB;\n")
            f.write("  node [shape=box, fontsize=10];\n")

            func_count = 0
            for func_ea in idautils.Functions():
                func_count += 1
                func_name = ida_name.get_name(func_ea)
                if not func_name or func_name.startswith("sub_"):
                    func_name = f"sub_{func_ea:x}"

                func = ida_funcs.get_func(func_ea)
                if not func:
                    continue

                # Создаем граф потоков для функции
                flow_chart = ida_gdl.qflow_chart_t("", func, func.start_ea, func.end_ea, 0)

                f.write(f"  subgraph cluster_{func_ea:x} {{\n")
                f.write(f"    label=\"{func_name}\";\n")
                f.write("    style=dashed;\n")

                for i in range(flow_chart.size()):
                    block = flow_chart[i]
                    block_id = f"{func_ea:x}_bb_{i}"
                    
                    # ИСПРАВЛЕНИЕ: Получаем преемников через методы flow_chart
                    num_succs = flow_chart.nsucc(i)
                    for j in range(num_succs):
                        succ_idx = flow_chart.succ(i, j)
                        succ_id = f"{func_ea:x}_bb_{succ_idx}"
                        f.write(f"    {block_id} -> {succ_id};\n")

                f.write("  }\n")

            f.write("}\n")
        idc.msg(f"        {output_file}\n")
        
    except Exception as e:
        import traceback
        idc.msg(traceback.format_exc())
    
    ida_pro.qexit(0)

if __name__ == "__main__":
    main()
