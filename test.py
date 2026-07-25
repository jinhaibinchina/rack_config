import os
import glob
import sys




def collect_files(pattern,target_dir):
    files = glob.glob(pattern,recursive = False)
    return [(f,target_dir) for f in files]

def collect_directory(source_dir,target_dir):

    result = []
    if not  os.path.exists(source_dir):
        print(f'源目录不存在：{source_dir}')
        return result
    
    if not os.path.isdir(source_dir):
        print(f'{source_dir}不是目录')
        return result

    for root , dirs, files in os.walk(source_dir):
        for file in files:
            source_file =  os.path.join(root,file)

            rel_path = os.path.relpath(source_file,source_dir)
            target_path = os.path.join(target_dir,os.path.dirname(rel_path))
            target_path = os.path.normpath(target_path).replace('\\','/')

            result.append((source_file,target_path))

    print(f'收集目录{source_dir} -> {target_dir}: 共{len(result)}  个文件')
    return result

if __name__ == '__main__':
    pass