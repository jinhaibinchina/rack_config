import subprocess
import re
import platform 

def scan_by_arp():
    """通过ARP表扫描局域网设备"""
    active_ips = []
    
    try:
        # 执行arp -a命令获取ARP表
        result = subprocess.run(["arp", "-a"], capture_output=True, text=True)
        
        # 解析ARP表输出
        # Windows和Linux/macOS的arp表格式不同
        if platform.system().lower() == "windows":
            # Windows格式
            pattern = r"(\d+\.\d+\.\d+\.\d+)\s+[0-9a-f-]+\s+动态"
        else:
            # Linux/macOS格式
            pattern = r"\((\d+\.\d+\.\d+\.\d+)\) at ([0-9a-f:]+)"
        
        matches = re.findall(pattern, result.stdout)
        
        for match in matches:
            if isinstance(match, tuple):
                ip = match[0]  # 对于Linux/macOS
            else:
                ip = match     # 对于Windows
            active_ips.append(ip)
            
        return sorted(set(active_ips))
        
    except Exception as e:
        print(f"ARP扫描错误: {e}")
        return []

# 使用方法
if __name__ == "__main__":
    print("通过ARP表扫描局域网设备...")
    arp_nodes = scan_by_arp()
    
    print(f"发现 {len(arp_nodes)} 个设备:")
    for ip in arp_nodes:
        print(f"  - {ip}")
