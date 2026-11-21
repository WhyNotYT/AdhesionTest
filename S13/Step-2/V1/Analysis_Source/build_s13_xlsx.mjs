import fs from 'node:fs/promises';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const root=process.env.S13_PROJECT_ROOT ?? '/workspace/scratch/e5a7a5c0c1d8';
const outputDir=`${root}/outputs/S13_Step2`;
await fs.mkdir(outputDir,{recursive:true});
const data=JSON.parse(await fs.readFile(`${root}/work/S13_Workbook_Data.json`,'utf8'));
const wb=Workbook.create();
const summary=wb.worksheets.add('Summary');
const detail=wb.worksheets.add('Per cell');
for(const sheet of [summary,detail]){
  sheet.showGridLines=false;
  sheet.getRange(sheet===summary?'A1:K34':'A1:M329').format.font={name:'Arial',size:10,color:'#142534'};
  sheet.getRange(sheet===summary?'A1:K34':'A1:M329').format.verticalAlignment='center';
}
summary.tabColor='#234D64';
const header=(sheet,range)=>{
 const r=sheet.getRange(range);
 r.format={fill:'#234D64',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},horizontalAlignment:'center',verticalAlignment:'center',wrapText:true,rowHeight:34};
 r.format.borders={insideVertical:{style:'thin',color:'#FFFFFF'}};
};

detail.getRange('A2').values=[['S13 per-cell measurements']];
detail.getRange('A2').format.font={size:14,bold:true};
detail.getRange('A3').values=[['Source: paired S13_Squared_[1–4].tif and S13_Taped_[1–4].tif. Native Taped pixels.']];
detail.getRange('A3').format.font={italic:true,size:10,color:'#4D6270'};
detail.getRange('A4:M4').values=[['Image','Cell ID','Row','Column','Grid pixels','Scrape excluded pixels','Existing foil excluded pixels','Eligible AM pixels','Loss pixels','Retained pixels','AM loss (%)','AM retained (%)','Cell status']];
header(detail,'A4:M4');
detail.getRange('A5:I328').values=data.cells.map(r=>[r.image,r.cell_id,r.row_from_top_1_based,r.column_from_left_1_based,r.grid_pixels,r.scrape_excluded_pixels,r.preexisting_foil_excluded_pixels,r.eligible_AM_pixels,r.loss_pixels]);
detail.getRange('J5:M5').formulas=[['=H5-I5','=IF(H5=0,"n.a.",I5/H5)','=IF(H5=0,"n.a.",J5/H5)','=IF(H5=0,"Excluded",IF(I5>0,"Damaged","Intact"))']];
detail.getRange('J5:M328').fillDown();
detail.getRange('B5:J328').setNumberFormat('#,##0');
detail.getRange('K5:L328').setNumberFormat('0.00%');
detail.getRange('M5:M328').conditionalFormats.add('containsText',{text:'Intact',format:{fill:'#FFF5A3'}});
detail.getRange('M5:M328').conditionalFormats.add('containsText',{text:'Damaged',format:{fill:'#FFD6A0'}});
detail.getRange('M5:M328').conditionalFormats.add('containsText',{text:'Excluded',format:{fill:'#FFB7B7'}});
detail.getRange('A5:M328').format.rowHeight=20;
detail.getRange('A4:M4').format.rowHeight=46;
const detailWidths=[148,63,55,63,91,105,114,107,93,106,100,112,105];
for(let j=0;j<detailWidths.length;j++)detail.getRangeByIndexes(0,j,329,1).format.columnWidthPx=detailWidths[j];
detail.freezePanes.freezeRows(4);
detail.freezePanes.freezeColumns(2);

summary.getRange('A2').values=[['S13 adhesion area estimate']];
summary.getRange('A2').format.font={size:14,bold:true};
summary.getRange('A3:K3').format.borders={bottom:{style:'thin',color:'#234D64'}};
summary.getRange('A4').values=[['High sensitivity. Four repeated views of one specimen. Original scrape bands excluded.']];
summary.getRange('A4').format.font={italic:true,color:'#4D6270'};
summary.getRange('A5:K5').values=[['Image','Rows','Columns','Total cells','No detected loss','Damaged cells','Excluded cells','AM retained (%)','AM loss (%)','Eligible AM pixels','Loss pixels']];
header(summary,'A5:K5');
const A="'Per cell'!$A$5:$A$328";
const M="'Per cell'!$M$5:$M$328";
const H="'Per cell'!$H$5:$H$328";
const I="'Per cell'!$I$5:$I$328";
for(let i=0;i<4;i++){
 const r=6+i;
 summary.getRange(`A${r}:C${r}`).values=[[data.summary[i].image,9,9]];
 summary.getRange(`D${r}:K${r}`).formulas=[[
  `=COUNTIFS(${A},A${r})`,
  `=COUNTIFS(${A},A${r},${M},"Intact")`,
  `=COUNTIFS(${A},A${r},${M},"Damaged")`,
  `=COUNTIFS(${A},A${r},${M},"Excluded")`,
  `=1-I${r}`,`=K${r}/J${r}`,`=SUMIFS(${H},${A},A${r})`,`=SUMIFS(${I},${A},A${r})`
 ]];
}
summary.getRange('A11').values=[['Mean of four views']];
summary.getRange('H11:I11').formulas=[['=AVERAGE(H6:H9)','=AVERAGE(I6:I9)']];
summary.getRange('A11:K11').format.fill='#E9F1F5';
summary.getRange('A11:K11').format.font={bold:true};
summary.getRange('H6:I11').setNumberFormat('0.00%');
summary.getRange('B6:G9').setNumberFormat('#,##0');
summary.getRange('J6:K9').setNumberFormat('#,##0');
summary.getRange('A6:K11').format.rowHeight=25;
summary.getRange('A14').values=[['Detection threshold comparison']];
summary.getRange('A14').format.font={bold:true};
summary.getRange('A15:D15').values=[['Image','High AM loss (%)','Moderate AM loss (%)','Conservative AM loss (%)']];
header(summary,'A15:D15');
summary.getRange('A15:D15').format.rowHeight=48;
for(let i=0;i<4;i++){
 const r=16+i;const ts=data.thresholds.filter(s=>s.image===data.summary[i].image);
 summary.getRange(`A${r}`).values=[[data.summary[i].image]];
 summary.getRange(`B${r}`).formulas=[[`=I${6+i}`]];
 summary.getRange(`C${r}:D${r}`).values=[[ts[1].loss_pct/100,ts[2].loss_pct/100]];
}
summary.getRange('A20').values=[['Mean']];
summary.getRange('B20:D20').formulas=[['=AVERAGE(B16:B19)','=AVERAGE(C16:C19)','=AVERAGE(D16:D19)']];
summary.getRange('B16:D20').setNumberFormat('0.00%');
summary.getRange('A20:D20').format.font={bold:true};
summary.getRange('A20:D20').format.fill='#E9F1F5';
summary.getRange('F15').values=[['Interpretation']];
summary.getRange('F15').format.font={bold:true};
summary.getRange('F16').values=[['No detected loss means zero pixels pass the selected rule.']];
summary.getRange('F17').values=[['Damaged includes cells with very small candidate regions.']];
summary.getRange('F18').values=[['Threshold comparison shows method sensitivity.']];
summary.getRange('F19').values=[['It is not a statistical confidence interval.']];
summary.getRange('F20').values=[['No whole cells excluded. Scrape pixels are excluded.']];

const notes=[
 ['Area definition','AM loss = new loss pixels / eligible original AM pixels. AM retained = 1 − AM loss.'],
 ['Primary setting','Paired increase > max(0.22, 2σ) in log intensity, local brightness ratio ≥ 1.5, ≥3 connected pixels.'],
 ['Moderate setting','Paired increase > max(0.22, 2.5σ), local brightness ratio ≥ 1.7.'],
 ['Conservative setting','Paired increase > max(0.22, 3σ), local brightness ratio ≥ 2.0.'],
 ['Limit','Fine bright features can reflect illumination or roughness. These are optical loss candidates.'],
 ['Repeat views','The four image estimates describe one 81-cell specimen. They are not four independent samples.'],
 ['Masks and method','Exact masks, source hashes, registration and full method are included in the accompanying ZIP.']
];
for(let i=0;i<notes.length;i++){
 const r=23+i;summary.getRange(`A${r}`).values=[[notes[i][0]]];summary.getRange(`B${r}`).values=[[notes[i][1]]];
 summary.getRange(`A${r}`).format.font={bold:true};
}
summary.getRange('A23:K29').format.rowHeight=24;
summary.getRange('A1:A34').format.columnWidthPx=155;
summary.getRange('B1:B34').format.columnWidthPx=118;
summary.getRange('C1:C34').format.columnWidthPx=129;
summary.getRange('D1:D34').format.columnWidthPx=139;
summary.getRange('E1:G34').format.columnWidthPx=103;
summary.getRange('H1:I34').format.columnWidthPx=117;
summary.getRange('J1:J34').format.columnWidthPx=133;
summary.getRange('K1:K34').format.columnWidthPx=105;
summary.getRange('B6:K11').format.horizontalAlignment='right';
summary.getRange('B16:D20').format.horizontalAlignment='right';
summary.getRange('F16:K20').format.horizontalAlignment='left';

wb.recalculate();
// Independent controls compare the formula results against the exact mask counts.
for(let i=0;i<4;i++){
 const r=6+i;const values=summary.getRange(`D${r}:K${r}`).values[0];const expected=data.summary[i];
 const truth=[81,expected.intact_no_detected_loss_cells,expected.damaged_cells,expected.excluded_cells,expected.retained_AM_pct/100,expected.peeled_AM_pct/100,expected.eligible_AM_pixels,expected.loss_pixels];
 values.forEach((v,j)=>{if(typeof v!=='number'||Math.abs(v-truth[j])>1e-9)throw new Error(`Summary ${r}, ${j}: ${v} != ${truth[j]}`)});
}
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:1500});
console.log(errors.ndjson);
console.log((await wb.inspect({kind:'table',range:'Summary!A5:K11',include:'values,formulas',tableMaxRows:7,tableMaxCols:11,maxChars:2500})).ndjson);
for(const [sheetName,range,filename] of [['Summary','A1:K29','Summary_QA.png'],['Per cell','A1:M16','Per_Cell_QA.png']]){
 const preview=await wb.render({sheetName,range,scale:1.3,format:'png'});
 await fs.writeFile(`${outputDir}/${filename}`,new Uint8Array(await preview.arrayBuffer()));
}
const xlsx=await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(`${outputDir}/S13_Step2_Results.xlsx`);
console.log(JSON.stringify({path:`${outputDir}/S13_Step2_Results.xlsx`,sheets:2,perCellRows:data.cells.length,verified:true}));
