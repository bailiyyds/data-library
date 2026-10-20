const $=s=>document.querySelector(s);
let state={folders:[],files:[]},current=null,type="all",query="",timer;
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n};
const category=name=>{const x=name.split(".").pop().toLowerCase();return ["png","jpg","jpeg","gif","webp","svg","bmp","tif","tiff"].includes(x)?"image":["ppt","pptx"].includes(x)?"ppt":["csv","tsv","xlsx","xls","json","txt"].includes(x)?"data":"other"};
const size=n=>n<1024?n+" B":n<1048576?(n/1024).toFixed(1)+" KB":(n/1048576).toFixed(1)+" MB";
function toast(s){$("#status").textContent=s;$("#status").hidden=false;clearTimeout(timer);timer=setTimeout(()=>$("#status").hidden=true,5000)}
async function api(path,body,raw=false){const r=await fetch(path,body===undefined?{}:{method:"POST",headers:{"X-Library-Request":"1",...(!raw?{"Content-Type":"application/json"}:{})},body:raw?body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||"请求失败");return data}
async function refresh(){state=await api("/api/library");render()}
const folderName=id=>state.folders.find(f=>f.id===id)?.name||"未分类";
function folderPath(id){const names=[];while(id){const f=state.folders.find(f=>f.id===id);if(!f)break;names.unshift(f.name);id=f.parent}return names.join(" / ")}
function select(id){current=id;render()}
function render(){
 const nav=$("#folders");nav.replaceChildren();
 const button=(name,id,depth=0)=>{const b=el("button",name,current===id?"selected":"");b.style.paddingLeft=12+depth*14+"px";b.onclick=()=>select(id);nav.append(b)};
 button("▦  全部文件",null);button("◇  未分类","unfiled");
 function tree(parent,depth){state.folders.filter(f=>f.parent===parent).forEach(f=>{button("▱  "+f.name,f.id,depth);tree(f.id,depth+1)})}tree(null,0);
 $("#title").textContent=current===null?"全部文件":current==="unfiled"?"未分类":folderName(current);
 $("#crumb").textContent=current&&current!=="unfiled"?folderPath(current):"工作空间中的所有资料";
 $("#removeFolder").hidden=!current||current==="unfiled";
 const stats=$("#stats");stats.replaceChildren();
 [["▦","全部资料",state.files.length],["▤","数据文件",state.files.filter(f=>category(f.name)==="data").length],["P","演示文稿",state.files.filter(f=>category(f.name)==="ppt").length],["▧","图片素材",state.files.filter(f=>category(f.name)==="image").length]].forEach(([icon,label,count])=>{const c=el("div",undefined,"stat"),v=el("div");v.append(el("strong",count),el("small",label));c.append(el("span",icon,"stat-icon"),v);stats.append(c)});
 const descendants=new Set([current]);let changed=true;while(changed){changed=false;for(const f of state.folders)if(descendants.has(f.parent)&&!descendants.has(f.id)){descendants.add(f.id);changed=true}}
 const files=state.files.filter(f=>(current===null||(current==="unfiled"?!f.folder:descendants.has(f.folder)))&&(type==="all"||category(f.name)===type)&&(f.name+" "+f.tags).toLowerCase().includes(query.toLowerCase()));
 $("#count").textContent=files.length+" 个文件";const list=$("#files");list.replaceChildren();
 if(!files.length){list.append(el("div",query||type!=="all"?"没有找到匹配的文件，请调整筛选条件。":"这里还没有资料\n点击「上传文件」或将文件拖入这里，开始整理。","empty"));return}
 for(const f of files){const row=el("div",undefined,"row"),name=el("div",undefined,"file-name"),text=el("div"),b=el("button",f.name);b.onclick=()=>openFile(f);text.append(b,el("small",f.tags||"暂无标签"));name.append(el("span",f.name.includes(".")?f.name.split(".").pop().toUpperCase().slice(0,5):"FILE","file-icon"),text);const meta=el("div",size(f.size),"meta");meta.append(el("small",f.created+" UTC"));const actions=el("div",undefined,"row-actions"),edit=el("button","整理"),download=el("button","下载");edit.onclick=()=>editFile(f);download.onclick=()=>location.href="/api/file/"+f.id+"?download=1";actions.append(edit,download);row.append(name,el("div",f.folder?folderPath(f.folder):"未分类","folder-cell"),meta,actions);list.append(row)}
}
function modal(title){$("#modalTitle").textContent=title;$("#preview").replaceChildren();if(!$("#modal").open)$("#modal").showModal();return $("#preview")}
async function openFile(f){const p=modal(f.name);try{if(/\.(png|jpe?g|webp|gif)$/i.test(f.name)){const img=el("img");img.alt=f.name;img.src="/api/file/"+f.id;p.append(img);return}p.textContent="正在读取…";const d=await api("/api/file/"+f.id+"?preview=1");p.replaceChildren();if(d.kind==="table"){p.append(el("p","预览前 100 行、40 列（最多读取 256 KB）。"));const t=el("table");for(const row of d.rows){const tr=el("tr");for(const val of row)tr.append(el("td",val));t.append(tr)}p.append(t)}else if(d.kind==="slides"){p.append(el("p","文字提取预览，共 "+d.total+" 页，最多显示前 100 页；不还原幻灯片版式。"));d.slides.forEach((s,i)=>{const section=el("section",undefined,"slide");section.append(el("strong","第 "+(i+1)+" 页"),el("pre",s||"本页没有可提取的文字"));p.append(section)})}else if(d.kind==="text"){p.append(el("p","文本预览，最多显示前 30,000 字符。"),el("pre",d.text))}else{p.append(el("p","此格式暂不支持在线预览，可下载后使用本机应用打开。"));const a=el("a","下载文件");a.href="/api/file/"+f.id+"?download=1";p.append(a)}}catch(e){p.textContent=e.message}}
function editFile(f){const p=modal("整理文件 · "+f.name),label=el("label","所属目录"),select=el("select");select.id="edit-folder";label.htmlFor=select.id;const none=el("option","未分类");none.value="";select.append(none);for(const folder of state.folders){const o=el("option",folderPath(folder.id));o.value=folder.id;select.append(o)}select.value=f.folder||"";const tagsLabel=el("label","标签（用空格或逗号分隔）"),tags=el("input");tags.id="edit-tags";tagsLabel.htmlFor=tags.id;tags.value=f.tags;const save=el("button","保存更改","primary"),del=el("button","删除文件");save.onclick=async()=>{try{await api("/api/update",{id:f.id,folder:select.value,tags:tags.value});$("#modal").close();await refresh();toast("已保存")}catch(e){toast(e.message)}};del.onclick=async()=>{if(!confirm("永久删除「"+f.name+"」？此操作不可撤销。"))return;try{await api("/api/delete",{id:f.id});$("#modal").close();await refresh();toast("文件已删除")}catch(e){toast(e.message)}};p.append(label,select,tagsLabel,tags,save,document.createTextNode(" "),del)}
async function upload(files){if(!files.length)return;$("#uploadButton").disabled=true;let ok=0,fail=0;for(const f of files){try{toast("正在上传："+f.name);if(f.size>50*1024*1024)throw Error("文件超过 50 MB");await api("/api/upload?"+new URLSearchParams({name:f.name,folder:current&&current!=="unfiled"?current:""}),f,true);ok++}catch(e){fail++;alert(f.name+"："+e.message)}}$("#uploadButton").disabled=false;$("#upload").value="";try{await refresh()}catch(e){toast(e.message);return}toast("上传完成："+ok+" 个成功"+(fail?"，"+fail+" 个失败":""))}
$("#uploadButton").onclick=()=>$("#upload").click();$("#upload").onchange=e=>upload([...e.target.files]);
$("#newFolder").onclick=async()=>{const name=prompt("新建目录名称（将创建在当前选中目录下）：");if(!name?.trim())return;try{await api("/api/folder",{name,parent:current&&current!=="unfiled"?current:null});await refresh();toast("目录已创建")}catch(e){toast(e.message)}};
$("#removeFolder").onclick=async()=>{if(!confirm("删除当前空目录？"))return;try{await api("/api/delete-folder",{id:current});current=null;await refresh()}catch(e){toast(e.message)}};
$("#search").oninput=e=>{query=e.target.value;render()};
$("#tabs").onclick=e=>{const b=e.target.closest("[data-type]");if(!b)return;type=b.dataset.type;$("#tabs").querySelectorAll("button").forEach(x=>x.classList.toggle("active",x===b));render()};
$("#closeModal").onclick=()=>$("#modal").close();
const drop=$("#dropzone");drop.ondragover=e=>{e.preventDefault();drop.classList.add("dragging")};drop.ondragleave=()=>drop.classList.remove("dragging");drop.ondrop=e=>{e.preventDefault();drop.classList.remove("dragging");upload([...e.dataTransfer.files])};
refresh().catch(e=>toast("无法连接本地服务："+e.message));
