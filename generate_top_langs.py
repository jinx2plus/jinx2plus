import re
import urllib.request

def main():
    url = "https://github-stats-extended.vercel.app/api/top-langs/?username=jinx2plus&layout=compact&theme=tokyonight&hide_border=true&hide=html"
    
    # Request header to pretend to be a browser (some APIs block python urllib user-agent)
    req = urllib.request.Request(
        url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            svg_data = response.read().decode('utf-8')
            
        def repl(m):
            val = float(m.group(2))
            return f"{m.group(1)} {int(round(val))}%"
            
        # 정규식을 이용해 소수점 퍼센트 탐색 후 반올림 적용
        modified_svg = re.sub(r"([^>\n\r]+?)\s+(\d+\.\d+)%", repl, svg_data)
        
        # 파일 저장
        with open("github-top-langs.svg", "w", encoding="utf-8") as f:
            f.write(modified_svg)
            
        print("Successfully generated and modified top-langs SVG!")
    except Exception as e:
        print(f"Error occurred: {e}")

if __name__ == "__main__":
    main()
