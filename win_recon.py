# win_recon.py
# Windows Recon Tool – Educational / Learning Purpose Only
# Run as Administrator for maximum results
# Last updated: March 2026

import platform
import socket
import getpass
import os
import json
import datetime
import psutil
import requests
import subprocess
import winreg
import wmi
import ctypes
from colorama import init, Fore, Style

init(autoreset=True)

# ────────────────────────────────────────────────
# CORE / ALWAYS COLLECTED (fast & essential)
# ────────────────────────────────────────────────

def get_system_info():
    info = {}
    info['os']         = platform.system()
    info['full_os']    = platform.platform()
    info['arch']       = platform.architecture()[0]
    info['hostname']   = socket.gethostname()
    info['username']   = getpass.getuser()
    info['is_admin']   = ctypes.windll.shell32.IsUserAnAdmin() != 0
    return info

def get_network_info():
    net = {}
    net['public_ip'] = "N/A"
    try:
        net['public_ip'] = requests.get("https://api.ipify.org", timeout=4).text
    except:
        pass
    return net

def get_hardware_info():
    hw = {}
    hw['cpu_percent'] = psutil.cpu_percent(interval=0.6)
    hw['ram'] = {k: round(v / (1024**3), 2) for k,v in psutil.virtual_memory()._asdict().items() if k in ['total','used','free','percent']}
    return hw

def get_running_processes(top=20):
    procs = []
    for p in psutil.process_iter(['pid','name','username','memory_info']):
        try:
            mem_mb = p.info['memory_info'].rss / (1024**2)
            procs.append({
                'pid': p.info['pid'],
                'name': p.info['name'],
                'user': p.info['username'] or 'N/A',
                'mem_mb': round(mem_mb,1)
            })
        except:
            pass
    procs.sort(key=lambda x: x['mem_mb'], reverse=True)
    return procs[:top]

def get_network_connections(max_show=12):
    conns = {'listen':[], 'active':[]}
    for c in psutil.net_connections(kind='inet'):
        try:
            p = psutil.Process(c.pid) if c.pid else None
            entry = {
                'local':  f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "N/A",
                'remote': f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else "N/A",
                'status': c.status,
                'pid':    c.pid,
                'proc':   p.name() if p else "N/A"
            }
            if c.status == 'LISTEN':
                conns['listen'].append(entry)
            elif c.status == 'ESTABLISHED':
                conns['active'].append(entry)
        except:
            pass
    return conns

def detect_security_products():
    common = ['MsMpEng','csagent','sentinelagent','csfalcon','edpa','mfemactl','carbonblack','cylance','avastsvc','avgnt','avguard','bdagent','ekrn','mbamservice','sophos','savservice','360tray']
    found = []
    for p in psutil.process_iter(['name']):
        name = p.info['name'].lower()
        if any(c in name for c in common):
            found.append(p.info['name'])
    return list(set(found))[:8]

# ────────────────────────────────────────────────
# ON-DEMAND MODULES (selected by user)
# ────────────────────────────────────────────────

def get_local_users_and_groups():
    try:
        c = wmi.WMI()
        users = [f"{u.Name} ({'Enabled' if not u.Disabled else 'Disabled'})" for u in c.Win32_UserAccount(LocalAccount=True)]
        groups = []
        for g in ["Administrators", "Remote Desktop Users"]:
            grp = c.Win32_Group(Name=g)
            if grp:
                members = [m.Name for m in grp[0].associators("Win32_GroupUser")]
                groups.append(f"{g}: {', '.join(members) or 'None'}")
        return {"users": users[:15], "groups": groups}
    except Exception as e:
        return {"error": str(e)}

def get_installed_software(top=45):
    software = []
    for base in [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    ]:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                    sk = winreg.OpenKey(key, sub)
                    name = winreg.QueryValueEx(sk, "DisplayName")[0] if "DisplayName" in [winreg.EnumValue(sk,j)[0] for j in range(winreg.QueryInfoKey(sk)[1])] else None
                    if name:
                        ver = winreg.QueryValueEx(sk, "DisplayVersion")[0] if "DisplayVersion" in [winreg.EnumValue(sk,j)[0] for j in range(winreg.QueryInfoKey(sk)[1])] else "?"
                        software.append(f"{name} ({ver})")
                    i += 1
                except OSError:
                    break
        except:
            pass
    return list(dict.fromkeys(software))[:top]

def get_scheduled_tasks(max_show=12):
    try:
        out = subprocess.check_output("schtasks /query /fo LIST /v", shell=True, stderr=subprocess.STDOUT, text=True)
        tasks = []
        current = {}
        for line in out.splitlines():
            line = line.strip()
            if "TaskName:" in line:
                if current: tasks.append(current)
                current = {"name": line.split(":",1)[1].strip()}
            elif "Next Run Time:" in line:
                current["next"] = line.split(":",1)[1].strip()
            elif "Author:" in line:
                current["author"] = line.split(":",1)[1].strip()
        if current: tasks.append(current)
        return tasks[:max_show]
    except Exception as e:
        return {"error": str(e)}

def get_windows_services(max_show=18):
    try:
        out = subprocess.check_output("sc query type= service state= all", shell=True, text=True)
        services = []
        current = {}
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("SERVICE_NAME:"):
                if current: services.append(current)
                current = {"name": line.split(":",1)[1].strip()}
            elif "STATE" in line and ":" in line:
                state = line.split(":",1)[1].strip().split()[0]
                current["state"] = state
            elif "BINARY_PATH_NAME" in line:
                current["path"] = line.split(":",1)[1].strip()
        if current: services.append(current)
        interesting = [s for s in services if s.get("state") in ("RUNNING", "4")][:max_show]
        return interesting
    except Exception as e:
        return {"error": str(e)}

def get_startup_autoruns():
    locations = []
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_CURRENT_USER,  r"Software\Microsoft\Windows\CurrentVersion\Run")
    ]
    for hive, path in keys:
        try:
            key = winreg.OpenKey(hive, path, 0, winreg.KEY_READ)
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    locations.append(f"{name} → {value}")
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except:
            pass
    return locations[:15]

def get_hotfixes():
    try:
        out = subprocess.check_output("wmic qfe list brief /format:list", shell=True, text=True)
        fixes = [line.strip() for line in out.splitlines() if "HotFixID=" in line]
        return fixes[:12]
    except:
        return ["Error retrieving hotfixes (try running as admin)"]

def get_wifi_profiles():
    try:
        out = subprocess.check_output("netsh wlan show profiles", shell=True, text=True)
        profiles = [line.split(":")[1].strip() for line in out.splitlines() if "All User Profile" in line]
        results = []
        for p in profiles[:8]:
            try:
                pwd_out = subprocess.check_output(f'netsh wlan show profile name="{p}" key=clear', shell=True, text=True)
                key = [l for l in pwd_out.splitlines() if "Key Content" in l]
                pwd = key[0].split(":")[1].strip() if key else "N/A"
                results.append(f"{p} → {pwd}")
            except:
                results.append(f"{p} → (password not retrieved)")
        return results
    except:
        return ["Error – run as admin or Wi-Fi not available"]

def get_interesting_files_hints():
    paths = [
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Downloads")
    ]
    hints = []
    keywords = ["pass", "pwd", "key", "token", "cred", "rdp"]
    for path in paths:
        try:
            for file in os.listdir(path):
                if any(k in file.lower() for k in keywords) and os.path.isfile(os.path.join(path, file)):
                    hints.append(os.path.join(path, file))
        except:
            pass
    return hints[:8]

# ────────────────────────────────────────────────
# MODULE REGISTRY
# ────────────────────────────────────────────────

MODULES = {
    1: {"name": "Local Users & Groups",        "func": get_local_users_and_groups},
    2: {"name": "Installed Software",          "func": get_installed_software},
    3: {"name": "Scheduled Tasks",             "func": get_scheduled_tasks},
    4: {"name": "Windows Services",            "func": get_windows_services},
    5: {"name": "Startup / Autorun Entries",   "func": get_startup_autoruns},
    6: {"name": "Installed Hotfixes / Updates","func": get_hotfixes},
    7: {"name": "Wi-Fi Profiles & Passwords",  "func": get_wifi_profiles},
    8: {"name": "Interesting Files (hints)",   "func": get_interesting_files_hints},
}

# ────────────────────────────────────────────────
# MENU + REPORT + SAVE
# ────────────────────────────────────────────────

def show_menu():
    print(f"\n{Fore.CYAN}Windows Recon Tool – Select features{Style.RESET_ALL}")
    print("───────────────────────────────────────────────")
    for k, v in sorted(MODULES.items()):
        print(f"[{k}] {v['name']}")
    print("\nall   → everything")
    print("q     → quit")
    print("───────────────────────────────────────────────")
    while True:
        inp = input(f"{Fore.GREEN}Choice → {Style.RESET_ALL}").strip().lower()
        if inp in ('q','quit','exit'):
            exit(0)
        if inp == 'all':
            return list(MODULES.keys())
        try:
            nums = [int(x) for x in inp.replace(',',' ').split() if x.isdigit()]
            nums = list(set(n for n in nums if n in MODULES))
            if nums: return nums
            print("Enter valid numbers or 'all'")
        except:
            print("Invalid format")

def print_report(data):
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S PKT')
    print(f"\n{Fore.CYAN}═══════════════════════════════════════════════")
    print(f"   Windows Recon Report • {ts}")
    print("═══════════════════════════════════════════════\n")

    s = data.get('system', {})
    n = data.get('network', {})
    print(f"{Fore.YELLOW}System Basics{Style.RESET_ALL}")
    print(f"  • OS       : {s.get('full_os','N/A')}")
    print(f"  • Host     : {s.get('hostname','N/A')}")
    print(f"  • User     : {s.get('username','N/A')} (admin: {s.get('is_admin')})")
    print(f"  • Public IP: {n.get('public_ip','N/A')}")

    if 'processes' in data:
        print(f"\n{Fore.YELLOW}Top Processes{Style.RESET_ALL}")
        for p in data['processes']:
            print(f"  • {p['name']:<22}  PID {p['pid']:>5}  {p['mem_mb']:>5.1f} MB")

    if 'connections' in data:
        print(f"\n{Fore.YELLOW}Listening Ports{Style.RESET_ALL}")
        for c in data['connections']['listen'][:10]:
            print(f"  • {c['local']:<22}  ← LISTEN  ({c['proc']})")

    for key, value in data.items():
        if key in ['system','network','processes','connections','timestamp']:
            continue
        title = key.replace('_',' ').title()
        print(f"\n{Fore.YELLOW}{title}{Style.RESET_ALL}")
        if isinstance(value, dict) and "error" in value:
            print(f"  {Fore.RED}Error: {value['error']}{Style.RESET_ALL}")
        elif isinstance(value, list):
            if not value:
                print("  (nothing found)")
            elif isinstance(value[0], dict):
                for item in value[:10]:
                    print("  • " + " | ".join(f"{k}: {v}" for k,v in item.items() if v))
            else:
                for item in value[:15]:
                    print(f"  • {item}")
        else:
            print(f"  {value}")

def save_json(data, fn="recon_report.json"):
    with open(fn, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"\n{Fore.GREEN}Report saved → {fn}{Style.RESET_ALL}")

def main():
    print(f"{Fore.MAGENTA}Windows Recon Tool – Educational Use Only{Style.RESET_ALL}\n")
    
    data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "system": get_system_info(),
        "network": get_network_info(),
        "hardware": get_hardware_info(),
        "processes": get_running_processes(),
        "connections": get_network_connections(),
        "security_products": detect_security_products(),
    }
    
    selected = show_menu()
    
    print(f"\n{Fore.CYAN}Collecting selected modules...{Style.RESET_ALL}\n")
    
    for num in selected:
        mod = MODULES[num]
        print(f"→ {mod['name']}")
        try:
            result = mod["func"]()
            key = mod["name"].lower().replace(" ","_").replace("/","")
            data[key] = result
        except Exception as e:
            data[mod["name"].lower().replace(" ","_")] = {"error": str(e)}
    
    print_report(data)
    save_json(data)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
    except Exception as e:
        print(f"\n{Fore.RED}Unexpected error: {e}{Style.RESET_ALL}")