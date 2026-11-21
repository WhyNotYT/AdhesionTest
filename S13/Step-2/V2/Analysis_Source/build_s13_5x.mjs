import fs from 'node:fs/promises';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root=process.env.S13_PROJECT_ROOT??'/workspace/scratch/e5a7a5c0c1d8';
const outputDir=`${root}/outputs/S13_Step2_5x`;
await fs.mkdir(outputDir,{recursive:true});
const data=JSON.parse(await fs.readFile(`${root}/work/S13_Workbook_Data_5x.json`,'utf8'));
const wb=Workbook.create();const summary=wb.worksheets.add('Summary');const detail=wb.worksheets.add('Per cell');
for(const [sheet,range] of [[summary,'A1:K32'],[detail,'A1:N329']]){
 sheet.showGridLines=false;sheet.getRange(range).format.font={name:'Arial',size:10,color:'#142534'};
 sheet.getRange(range).format.verticalAlignment='center';
}
summary.tabColor='#234D64';
function header(sheet,range){
 sheet.getRange(range).format={fill:'#234D64',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},horizontalAlignment:'center',verticalAlignment:'center',wrapText:true,rowHeight:45};
 sheet.getRange(range).format.borders={insideVertical:{style:'thin',color:'#FFFFFF'}};
}
detail.getRange('A2').values=[['S13 per-cell candidate loss at 5.0× sensitivity']];detail.getRange('A2').format.font={size:14,bold:true};
detail.getRange('A3').values=[['Source: paired S13_Squared_[1–4].tif and S13_Taped_[1–4].tif. Original eligible-area masks and registration retained.']];
detail.getRange('A3').format.font={italic:true,color:'#4D6270'};
detail.getRange('A4:N4').values=[['Image','Cell ID','Row','Column','Eligible AM pixels','Previous loss pixels','5× candidate loss pixels','Additional pixels','5× remaining pixels','Previous loss (%)','5× candidate loss (%)','5× remaining (%)','Increase (pp)','Cell status']];
header(detail,'A4:N4');detail.getRange('A4:N4').format.rowHeight=50;
detail.getRange('A5:G328').values=data.cells.map(r=>[r.image,r.cell_id,r.row_from_top_1_based,r.column_from_left_1_based,r.eligible_AM_pixels,r.baseline_loss_pixels,r.loss_pixels]);
detail.getRange('H5:N5').formulas=[['=G5-F5','=E5-G5','=IF(E5=0,"n.a.",F5/E5)','=IF(E5=0,"n.a.",G5/E5)','=IF(E5=0,"n.a.",I5/E5)','=IF(E5=0,"n.a.",(K5-J5)*100)','=IF(E5=0,"Excluded",IF(G5>0,"Damaged","Intact"))']];
detail.getRange('H5:N328').fillDown();
detail.getRange('B5:I328').setNumberFormat('#,##0');detail.getRange('J5:L328').setNumberFormat('0.00%');detail.getRange('M5:M328').setNumberFormat('0.00');
detail.getRange('A5:N328').format.rowHeight=20;
for(const [text,fill] of [['Intact','#FFF5A3'],['Damaged','#FFD6A0'],['Excluded','#FFB7B7']])detail.getRange('N5:N328').conditionalFormats.add('containsText',{text,format:{fill}});
const widths=[148,62,54,62,104,105,112,100,112,105,112,112,95,100];
widths.forEach((width,j)=>detail.getRangeByIndexes(0,j,329,1).format.columnWidthPx=width);
detail.freezePanes.freezeRows(4);detail.freezePanes.freezeColumns(2);

summary.getRange('A2').values=[['S13 candidate material loss at 5.0× sensitivity']];summary.getRange('A2').format.font={size:14,bold:true};
summary.getRange('A3:K3').format.borders={bottom:{style:'thin',color:'#234D64'}};
summary.getRange('A4').values=[['Both contrast thresholds divided by 5. Original scrape bands excluded. Four repeated views of one specimen.']];summary.getRange('A4').format.font={italic:true,color:'#4D6270'};
summary.getRange('A5:K5').values=[['Image','Rows','Columns','Total cells','No detected loss','Damaged cells','Excluded cells','5× remaining (%)','5× candidate loss (%)','Eligible AM pixels','5× loss pixels']];header(summary,'A5:K5');
const A="'Per cell'!$A$5:$A$328",E="'Per cell'!$E$5:$E$328",G="'Per cell'!$G$5:$G$328",N="'Per cell'!$N$5:$N$328";
for(let i=0;i<4;i++){
 const r=6+i;summary.getRange(`A${r}:C${r}`).values=[[data.summary[i].image,9,9]];
 summary.getRange(`D${r}:K${r}`).formulas=[[
 `=COUNTIFS(${A},A${r})`,`=COUNTIFS(${A},A${r},${N},"Intact")`,`=COUNTIFS(${A},A${r},${N},"Damaged")`,`=COUNTIFS(${A},A${r},${N},"Excluded")`,
 `=1-I${r}`,`=K${r}/J${r}`,`=SUMIFS(${E},${A},A${r})`,`=SUMIFS(${G},${A},A${r})`]];
}
summary.getRange('A11').values=[['Mean of four views']];summary.getRange('H11:I11').formulas=[['=AVERAGE(H6:H9)','=AVERAGE(I6:I9)']];
summary.getRange('A11:K11').format.fill='#E9F1F5';summary.getRange('A11:K11').format.font={bold:true};
summary.getRange('H6:I11').setNumberFormat('0.00%');summary.getRange('B6:G9').setNumberFormat('#,##0');summary.getRange('J6:K9').setNumberFormat('#,##0');summary.getRange('A6:K11').format.rowHeight=25;
summary.getRange('A14').values=[['Previous and updated detection']];summary.getRange('A14').format.font={bold:true};
summary.getRange('A15:D15').values=[['Image','Previous loss (%)','5× candidate loss (%)','Increase (pp)']];header(summary,'A15:D15');
for(let i=0;i<4;i++){
 const r=16+i;summary.getRange(`A${r}:B${r}`).values=[[data.summary[i].image,data.summary[i].baseline_loss_pct/100]];
 summary.getRange(`C${r}:D${r}`).formulas=[[`=I${6+i}`,`=(C${r}-B${r})*100`]];
}
summary.getRange('A20').values=[['Mean']];summary.getRange('B20:D20').formulas=[['=AVERAGE(B16:B19)','=AVERAGE(C16:C19)','=AVERAGE(D16:D19)']];
summary.getRange('B16:C20').setNumberFormat('0.00%');summary.getRange('D16:D20').setNumberFormat('0.00');summary.getRange('A20:D20').format.fill='#E9F1F5';summary.getRange('A20:D20').format.font={bold:true};
summary.getRange('F15').values=[['Interpretation']];summary.getRange('F15').format.font={bold:true};
const interpretation=['The new paired threshold equals 0.4σ of measured variation.','It admits fine texture and lighting changes.','Blue marks candidate material-loss pixels.','All 81 cells contain at least one candidate component.','No whole cells excluded. Original scrape masks retained.'];
interpretation.forEach((s,i)=>summary.getRange(`F${16+i}`).values=[[s]]);
const notes=[
 ['5.0× definition','Divide both previous positive log-contrast thresholds by 5.0 and reclassify the pixels.'],
 ['Paired threshold','Previous max(0.22, 2σ) / 5.0. The complete previous threshold is divided by five.'],
 ['Brightness threshold','Previous log(1.5) / 5.0. This corresponds to a local brightness ratio of 1.0844717712.'],
 ['Pixel clusters','Eight-connected components of at least three pixels. Blue masks are not expanded for display.'],
 ['Area definition','Candidate loss = selected pixels / eligible original AM pixels. Remaining estimate = 1 − candidate loss.'],
 ['Limit','These lower thresholds are within normal image variation. Fine bright features may reflect texture or illumination.'],
 ['Repeated views','The four views describe one physical 81-cell specimen. The mean is a repeated-view estimate.'],
 ['Comparison','Five times detector sensitivity does not imply five times selected area. The masks determine the percentages.']
];
notes.forEach(([label,text],i)=>{const r=23+i;summary.getRange(`A${r}`).values=[[label]];summary.getRange(`A${r}`).format.font={bold:true};summary.getRange(`B${r}`).values=[[text]];});
summary.getRange('A23:K30').format.rowHeight=24;
const summaryWidths=[155,118,139,135,103,103,103,121,125,133,105];summaryWidths.forEach((w,j)=>summary.getRangeByIndexes(0,j,32,1).format.columnWidthPx=w);
summary.getRange('B6:K11').format.horizontalAlignment='right';summary.getRange('B16:D20').format.horizontalAlignment='right';

wb.recalculate();
for(let i=0;i<4;i++){
 const r=6+i,s=data.summary[i],v=summary.getRange(`D${r}:K${r}`).values[0];
 const expected=[81,s.intact_no_detected_loss_cells,s.damaged_cells,s.excluded_cells,s.retained_AM_pct/100,s.peeled_AM_pct/100,s.eligible_AM_pixels,s.loss_pixels];
 v.forEach((n,j)=>{if(typeof n!=='number'||Math.abs(n-expected[j])>1e-9)throw new Error(`Summary ${r}/${j} mismatch`)});
}
for(const index of [0,161,323]){
 const r=index+5,v=detail.getRange(`H${r}:M${r}`).values[0],s=data.cells[index];
 const expected=[s.additional_loss_pixels,s.retained_pixels,s.baseline_loss_pct/100,s.loss_pct/100,s.retained_pct/100,s.increase_percentage_points];
 v.forEach((n,j)=>{if(typeof n!=='number'||Math.abs(n-expected[j])>1e-9)throw new Error(`Per cell ${r}/${j} mismatch`)});
}
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:1000})).ndjson);
console.log((await wb.inspect({kind:'table',range:'Summary!A5:K11',include:'values,formulas',tableMaxRows:7,tableMaxCols:11,maxChars:2500})).ndjson);
for(const [sheetName,range,name] of [['Summary','A1:K30','Summary_5x_QA.png'],['Per cell','A1:N16','Per_Cell_5x_QA.png']]){
 const image=await wb.render({sheetName,range,scale:1.2,format:'png'});await fs.writeFile(`${outputDir}/${name}`,new Uint8Array(await image.arrayBuffer()));
}
const xlsx=await SpreadsheetFile.exportXlsx(wb);await xlsx.save(`${outputDir}/S13_Step2_Results_5x.xlsx`);
console.log(JSON.stringify({path:`${outputDir}/S13_Step2_Results_5x.xlsx`,verified:true,records:data.cells.length}));
