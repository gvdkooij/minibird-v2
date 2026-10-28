const lines=document.getElementById('lines');
document.getElementById('add').addEventListener('click',()=>{if(lines.children.length>=100)return;const line=lines.firstElementChild.cloneNode(true);line.querySelector('[name=description]').value='';line.querySelector('[name=price]').value='';lines.append(line);});
lines.addEventListener('click',event=>{if(event.target.classList.contains('remove')&&lines.children.length>1)event.target.closest('fieldset').remove();});
