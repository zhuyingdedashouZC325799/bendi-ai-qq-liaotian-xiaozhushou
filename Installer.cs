using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

class Installer : Form {
    TextBox install=new TextBox(), models=new TextBox(), voices=new TextBox(), cache=new TextBox(), owners=new TextBox(), botqq=new TextBox(), name=new TextBox(), persona=new TextBox(), bridgePath=new TextBox();
    ComboBox profile=new ComboBox(), bridge=new ComboBox(), gpu=new ComboBox();
    CheckBox cover=new CheckBox(), consent=new CheckBox();
    Button action=new Button();TextBox log=new TextBox(); Label status=new Label();
    bool running=false;string settingsFile;JavaScriptSerializer serializer=new JavaScriptSerializer();
    static string Q(string value){return "\""+value.Replace("\"","\\\"")+"\"";}
    void Field(Panel panel,string title,Control control,int y,bool browse=false){
        var label=new Label(){Text=title,Left=22,Top=y+5,Width=155};panel.Controls.Add(label);
        control.SetBounds(182,y,650,27);control.Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right;panel.Controls.Add(control);
        if(browse){control.Width=570;var button=new Button(){Text="浏览…",Left=762,Top=y,Width=70,Height=27};button.Click+=(s,e)=>{using(var dialog=new FolderBrowserDialog()){dialog.Description=title;if(Directory.Exists(control.Text))dialog.SelectedPath=control.Text;if(dialog.ShowDialog()==DialogResult.OK)control.Text=dialog.SelectedPath;}};panel.Controls.Add(button);}
    }
    public Installer(){
        Text="本地 QQ 智能助手 · 在线安装";Size=new Size(900,880);MinimumSize=new Size(870,760);StartPosition=FormStartPosition.CenterScreen;Font=new Font("Microsoft YaHei UI",9F);BackColor=Color.White;
        var panel=new Panel(){Dock=DockStyle.Fill,AutoScroll=true};Controls.Add(panel);
        panel.Controls.Add(new Label(){Text="本地 QQ 智能助手",Font=new Font(Font.FontFamily,20,FontStyle.Bold),Left=20,Top=14,Width=780,Height=42});
        panel.Controls.Add(new Label(){Text="独立配置 · 在线安装依赖 · 使用自己的账号登录",Left=24,Top=60,Width=800,Height=25,ForeColor=Color.DimGray});
        var drive=DriveInfo.GetDrives().Where(d=>d.IsReady&&d.DriveType==DriveType.Fixed).OrderByDescending(d=>d.AvailableFreeSpace).FirstOrDefault();
        string data=(drive==null?Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData):drive.RootDirectory.FullName);
        install.Text=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"LocalQQAssistant");models.Text=Path.Combine(data,"LocalBotModels");voices.Text=Path.Combine(data,"LocalBotVoices");cache.Text=Path.Combine(data,"LocalBotCache");name.Text="本地助手";
        Field(panel,"程序安装目录",install,98,true);Field(panel,"大模型存放目录",models,136,true);Field(panel,"PTH / INDEX 音色目录",voices,174,true);Field(panel,"下载与缓存目录",cache,212,true);
        Field(panel,"机器人名称",name,250);Field(panel,"主人 QQ 号",owners,288);owners.AccessibleDescription="多个主人QQ号使用英文逗号分隔";
        Field(panel,"机器人自己的 QQ",botqq,326);
        profile.Items.AddRange(new object[]{"中性助手（无预设人设）","自定义人设"});profile.DropDownStyle=ComboBoxStyle.DropDownList;profile.SelectedIndex=0;Field(panel,"人设设置",profile,364);
        persona.Multiline=true;persona.ScrollBars=ScrollBars.Vertical;Field(panel,"自定义人设内容",persona,402);persona.Height=70;persona.Enabled=false;
        profile.SelectedIndexChanged+=(s,e)=>{persona.Enabled=profile.SelectedIndex==1;if(!persona.Enabled)persona.Text="";};
        bridge.Items.AddRange(new object[]{"NapCat 官方独立安装入口（自动准备）","连接已独立安装的 SnowLuma"});bridge.DropDownStyle=ComboBoxStyle.DropDownList;bridge.SelectedIndex=0;Field(panel,"QQ 接入方案",bridge,486);
        Field(panel,"已有 SnowLuma 目录",bridgePath,524,true);bridgePath.Enabled=false;bridge.SelectedIndexChanged+=(s,e)=>bridgePath.Enabled=bridge.SelectedIndex==1;
        cover.Text="安装翻唱组件（UVR5 / RVC；需自行提供 PTH 和 INDEX）";cover.SetBounds(182,562,650,28);cover.Checked=true;panel.Controls.Add(cover);
        gpu.Items.AddRange(new object[]{"CPU 通用版（所有电脑可用，较慢）","NVIDIA CUDA 版（需兼容显卡及驱动）"});gpu.DropDownStyle=ComboBoxStyle.DropDownList;gpu.SelectedIndex=0;Field(panel,"翻唱计算环境",gpu,596);
        consent.Text="我同意安装所选第三方组件；使用自己的 QQ 与 QQ 音乐登录";consent.SetBounds(22,638,810,30);panel.Controls.Add(consent);
        var links=new LinkLabel(){Text="组件来源、许可与登录说明",Left=24,Top=672,Width=400};links.LinkClicked+=(s,e)=>MessageBox.Show("核心：AstrBot（AGPL）\n模型：Ollama / Qwen 官方下载\n翻唱：RVC / UVR5 开源组件\nQQ 接入：NapCat 官方安装入口，或你已有的 SnowLuma。\nSnowLuma 不随本安装包分发，也不由脚本自动部署。\n机器人 QQ 与 QQ 音乐必须分别登录；不会继承任何人的登录状态。\n详细来源见安装目录 THIRD_PARTY.md。","第三方组件");panel.Controls.Add(links);
        var snowLink=new LinkLabel(){Text="SnowLuma 官方下载",Left=420,Top=672,Width=160};snowLink.LinkClicked+=(s,e)=>Process.Start(new ProcessStartInfo("https://github.com/SnowLuma/SnowLuma/releases"){UseShellExecute=true});panel.Controls.Add(snowLink);
        action.Text="确认并开始在线安装";action.SetBounds(590,665,242,36);action.Click+=async(s,e)=>await Install();panel.Controls.Add(action);
        status.SetBounds(24,713,810,25);status.Text="首次下载可能较大；失败会生成错误报告，可以重试。";panel.Controls.Add(status);
        log.SetBounds(24,744,808,220);log.Multiline=true;log.ReadOnly=true;log.ScrollBars=ScrollBars.Vertical;log.BackColor=Color.FromArgb(25,28,34);log.ForeColor=Color.Gainsboro;log.Font=new Font("Consolas",9);panel.Controls.Add(log);
        panel.AutoScrollMinSize=new Size(0,980);
        FormClosing+=(s,e)=>{if(running){MessageBox.Show("正在安装，请等待完成；当前下载会记录在所选缓存目录。 ");e.Cancel=true;}};
    }
    void Write(string line){if(IsDisposed)return;if(InvokeRequired){BeginInvoke(new Action<string>(Write),line);return;}if(log.TextLength>500000)log.Text=log.Text.Substring(log.TextLength-250000);log.AppendText(line+Environment.NewLine);}
    bool ValidateForm(){
        if(!consent.Checked){MessageBox.Show("请先确认所选组件的安装和账号登录说明。");return false;}
        string[] ids=Regex.Split(owners.Text.Trim(),@"[,，;；\s]+");
        if(ids.Length==0||ids.Any(v=>!Regex.IsMatch(v,@"^[1-9][0-9]{4,11}$"))){MessageBox.Show("请填写主人 QQ 号，多个号码用逗号分隔。");return false;}
        if(!Regex.IsMatch(botqq.Text.Trim(),@"^[1-9][0-9]{4,11}$")){MessageBox.Show("请填写要登录机器人的 QQ 号（可与主人号不同）。");return false;}
        foreach(var box in new[]{install,models,voices,cache}){
            try{box.Text=Path.GetFullPath(box.Text.Trim());if(box.Text==Path.GetPathRoot(box.Text)||box.Text.StartsWith(Environment.GetFolderPath(Environment.SpecialFolder.Windows),StringComparison.OrdinalIgnoreCase))throw new Exception();}
            catch{MessageBox.Show("请选择有效的独立文件夹，不能直接选择磁盘根目录或 Windows 目录。");return false;}
        }
        if(Directory.Exists(install.Text)&&Directory.EnumerateFileSystemEntries(install.Text).Any()&&!File.Exists(Path.Combine(install.Text,".localbot-package"))){MessageBox.Show("程序安装目录不是空目录，请选择新的文件夹，避免覆盖现有文件。");return false;}
        if(bridge.SelectedIndex==1&&!File.Exists(Path.Combine(bridgePath.Text,"index.mjs"))){MessageBox.Show("请先独立安装 SnowLuma，再选择含 index.mjs 的目录。");return false;}
        return true;
    }
    void ExtractPayload(string destination){
        using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("Payload"))
        using(var archive=new ZipArchive(stream,ZipArchiveMode.Read)){
            string prefix=Path.GetFullPath(destination).TrimEnd('\\')+"\\";
            foreach(var entry in archive.Entries){
                string path=Path.GetFullPath(Path.Combine(destination,entry.FullName.Replace('/',Path.DirectorySeparatorChar)));
                if(!path.StartsWith(prefix,StringComparison.OrdinalIgnoreCase))throw new IOException("非法安装路径");
                if(entry.FullName.EndsWith("/")){Directory.CreateDirectory(path);continue;}
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                using(var input=entry.Open())using(var output=File.Create(path))input.CopyTo(output);
            }
        }
    }
    async Task Install(){
        if(!ValidateForm())return;running=true;action.Enabled=false;status.Text="正在准备安装…";
        try{
            string destination=install.Text;Directory.CreateDirectory(destination);ExtractPayload(destination);
            string self=Assembly.GetExecutingAssembly().Location;string installed=Path.Combine(destination,"本地QQ助手.exe");
            if(!Path.GetFullPath(self).Equals(Path.GetFullPath(installed),StringComparison.OrdinalIgnoreCase))File.Copy(self,installed,true);
            settingsFile=Path.Combine(destination,"localbot.json");
            var data=new Dictionary<string,object>{{"install_dir",destination},{"models_dir",models.Text},{"voices_dir",voices.Text},{"cache_dir",cache.Text},{"owners",Regex.Split(owners.Text.Trim(),@"[,，;；\s]+").Distinct().ToArray()},{"bot_qq",botqq.Text.Trim()},{"bot_name",name.Text.Trim()},{"persona",profile.SelectedIndex==1?persona.Text:""},{"bridge_type",bridge.SelectedIndex==0?"napcat":"snowluma"},{"bridge_path",bridgePath.Text},{"enable_cover",cover.Checked},{"gpu_mode",gpu.SelectedIndex==1?"nvidia":"cpu"}};
            File.WriteAllText(settingsFile,serializer.Serialize(data),new UTF8Encoding(false));
            status.Text="正在下载并配置组件，请查看下方实时日志。";
            int code=await Task.Run(()=>{
                var info=new ProcessStartInfo("powershell.exe","-NoLogo -NoProfile -ExecutionPolicy Bypass -File "+Q(Path.Combine(destination,"scripts","install.ps1"))+" -ConfigFile "+Q(settingsFile)){UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8,WorkingDirectory=destination};
                using(var process=new Process(){StartInfo=info}){process.OutputDataReceived+=(s,e)=>{if(e.Data!=null)Write(e.Data);};process.ErrorDataReceived+=(s,e)=>{if(e.Data!=null)Write(e.Data);};process.Start();process.BeginOutputReadLine();process.BeginErrorReadLine();process.WaitForExit();return process.ExitCode;}
            });
            if(code!=0)throw new Exception("依赖安装未完成。错误报告位于 "+Path.Combine(cache.Text,"logs","error-reports"));
            status.Text="安装完成。使用桌面快捷方式启动，首次需要登录自己的账号。";MessageBox.Show(status.Text,"安装完成");
        }catch(Exception error){
            status.Text="安装未完成";Write(error.ToString());
            try{var folder=Path.Combine(cache.Text,"logs","error-reports");Directory.CreateDirectory(folder);File.WriteAllText(Path.Combine(folder,"installer-"+DateTime.Now.ToString("yyyyMMdd-HHmmss")+".txt"),error.ToString(),Encoding.UTF8);}catch{}
            MessageBox.Show(error.Message,"安装失败",MessageBoxButtons.OK,MessageBoxIcon.Error);
        }finally{running=false;action.Enabled=true;}
    }
    [STAThread] static void Main(string[] args){
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        if(args.Length>0&&args[0]=="--run"){
            string root=Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
            try{
                var configuration=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(root,"localbot.json"),Encoding.UTF8));
                if(!configuration.ContainsKey("installation_complete")||!Convert.ToBoolean(configuration["installation_complete"]))throw new IOException("安装尚未完成，请重新运行原始安装包继续安装。");
            }catch(Exception error){MessageBox.Show(error.Message,"需要安装或修复");return;}
            Process.Start(new ProcessStartInfo("powershell.exe","-NoLogo -NoProfile -ExecutionPolicy Bypass -File "+Q(Path.Combine(root,"scripts","run.ps1"))+" -ConfigFile "+Q(Path.Combine(root,"localbot.json"))){UseShellExecute=true,WorkingDirectory=root});return;
        }
        using(var form=new Installer()){
            if(args.Length==2&&args[0]=="--extract-test"){
                if(Directory.Exists(args[1])&&Directory.EnumerateFileSystemEntries(args[1]).Any())throw new IOException("Test target must be empty");
                Directory.CreateDirectory(args[1]);form.ExtractPayload(args[1]);return;
            }
            if(args.Length==2&&args[0]=="--preview"){
                form.Opacity=0;form.ShowInTaskbar=false;form.Show();Application.DoEvents();using(var bitmap=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(bitmap,new Rectangle(0,0,bitmap.Width,bitmap.Height));bitmap.Save(args[1]);}form.Hide();return;
            }
            Application.Run(form);
        }
    }
}
