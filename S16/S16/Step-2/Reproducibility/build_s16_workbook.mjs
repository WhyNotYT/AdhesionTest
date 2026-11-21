import fs from 'node:fs/promises';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';

const root=process.env.S16_WORK_DIR ?? process.cwd();
const outputDir=`${root}/outputs/S16_Step2`;
const results=JSON.parse(await fs.readFile(`${root}/analysis/segmentation_results.json`,'utf8'));
const registration=JSON.parse(await fs.readFile(`${root}/analysis/registration_summary.json`,'utf8'));
const wb=Workbook.create();
const summary=wb.worksheets.add('Summary');
const cells=wb.worksheets.add('Cells');
for (const sh of [summary,cells]) sh.showGridLines=false;
summary.tabColor='#284F3D';
summary.getRange('A1:K42').format.font={name:'Arial',size:11,color:'#20372B'};
cells.getRange('A1:R325').format.font={name:'Arial',size:10,color:'#24362C'};
summary.getRange('A2').values=[['S16 | Adhesion image-area estimate']];
summary.getRange('A2').format.font={size:16,bold:true,color:'#1F4432'};
summary.getRange('A3').values=[['High sensitivity | original grooves excluded | cells numbered 0–80']];
summary.getRange('A3').format.font={italic:true,color:'#58695E'};
summary.getRange('A5:K5').values=[['Image','Grid\ncolumns','Grid\nrows','Total\ncells','Intact*\ncells','Damaged\ncells','Excluded\ncells','Estimated\nAM loss','Retained\nAM area','Stricter\nAM loss','Bright-change\nsubset']];
summary.getRange('A5:K5').format={fill:'#284F3D',font:{bold:true,color:'#FFFFFF'},wrapText:true,horizontalAlignment:'center',verticalAlignment:'center',rowHeight:34};
summary.getRange('A5:K5').format.borders={insideVertical:{style:'thin',color:'#FFFFFF'}};
summary.getRange('A6:G9').values=results.map(r=>[r.image,9,9,null,null,null,null]);
summary.getRange('A6:A9').setNumberFormat('"Image "0');
summary.getRange('B6:G9').setNumberFormat('0');
summary.getRange('H6:K11').setNumberFormat('0.00%');
summary.getRange('A6:K11').format.rowHeight=26;
for (let j=0;j<4;j++) {
  const r=6+j,ar=16+j;
  summary.getRange(`D${r}:K${r}`).formulas=[[
    `=COUNTIFS(Cells!$A$2:$A$325,$A${r})`,
    `=COUNTIFS(Cells!$A$2:$A$325,$A${r},Cells!$E$2:$E$325,"Intact")`,
    `=COUNTIFS(Cells!$A$2:$A$325,$A${r},Cells!$E$2:$E$325,"Damaged")`,
    `=COUNTIFS(Cells!$A$2:$A$325,$A${r},Cells!$E$2:$E$325,"Excluded")`,
    `=C${ar}/B${ar}`,`=D${ar}/B${ar}`,
    `=SUMIFS(Cells!$M$2:$M$325,Cells!$A$2:$A$325,$A${r})/B${ar}`,
    `=SUMIFS(Cells!$O$2:$O$325,Cells!$A$2:$A$325,$A${r})/B${ar}`
  ]];
}
summary.getRange('A11').values=[['Four-photo mean']];
summary.getRange('H11:K11').formulas=[['=AVERAGE(H6:H9)','=AVERAGE(I6:I9)','=AVERAGE(J6:J9)','=AVERAGE(K6:K9)']];
summary.getRange('A11:K11').format.font={bold:true};
summary.getRange('H6:H11').format.fill='#DBEFFA';
summary.getRange('I6:I11').format.fill='#E7F0E7';
summary.getRange('J6:K11').format.font={color:'#536659'};
summary.getRange('A14').values=[['Calculation area (pixels)']];
summary.getRange('A14').format.font={bold:true,size:12};
summary.getRange('A15:E15').values=[['Image','Eligible AM','Estimated loss','Retained AM','Original grooves']];
summary.getRange('A15:E15').format={fill:'#E3EAE5',font:{bold:true},horizontalAlignment:'center',rowHeight:25};
for (let j=0;j<4;j++) {
  const r=16+j,s=6+j;
  summary.getRange(`A${r}:E${r}`).formulas=[[
    `=A${s}`,`=SUMIFS(Cells!$H$2:$H$325,Cells!$A$2:$A$325,$A${r})`,
    `=SUMIFS(Cells!$I$2:$I$325,Cells!$A$2:$A$325,$A${r})`,`=B${r}-C${r}`,
    `=SUMIFS(Cells!$G$2:$G$325,Cells!$A$2:$A$325,$A${r})`
  ]];
}
summary.getRange('A16:A19').setNumberFormat('"Image "0');
summary.getRange('B16:E19').setNumberFormat('#,##0');
summary.getRange('A16:E19').format.rowHeight=24;
summary.getRange('A22').values=[['Interpretation']];summary.getRange('A22').format.font={bold:true};
const notes=[
  '* Intact cell = no loss pixels detected at the stated thresholds.',
  'Dark new pits are included as probable coating loss; exposed Al is not independently confirmed in every pit.',
  'Stricter loss is a threshold comparison, not a confidence interval. Four photos depict one specimen.',
  'Loss and retention are area ratios within eligible AM, not fractions of the cells counted.'
];
summary.getRange('A23:A26').values=notes.map(s=>[s]);summary.getRange('A23:K26').format.rowHeight=23;
summary.getRange('A28').values=[['Source pairs']];summary.getRange('A28').format.font={bold:true};
summary.getRange('A29').values=[['Pair']];summary.getRange('B29').values=[['Squared reference']];summary.getRange('F29').values=[['Taped image']];
for(let j=0;j<4;j++) {const r=30+j;summary.getRange(`A${r}`).values=[[j+1]];summary.getRange(`B${r}`).values=[[`S16_Squared_[${j+1}].tif`]];summary.getRange(`F${r}`).values=[[`S16_Taped_[${j+1}].tif`]];}
summary.getRange('A35').values=[['Alignment verification (pixels)']];summary.getRange('A35').format.font={bold:true};
summary.getRange('A36:D36').values=[['Pair','Median mismatch','95th percentile','Matched patches']];
summary.getRange('A36:D36').format={fill:'#E3EAE5',font:{bold:true},horizontalAlignment:'center',rowHeight:25};
summary.getRange('A37:D40').values=registration.map(r=>[r.pair,r.median_residual_px,r.p95_residual_px,r.inlier_match_count]);
summary.getRange('B37:C40').setNumberFormat('0.00');
summary.getRange('A42').values=[['Full detection rules, masks and limitations: S16_Step2_Results_and_Method.txt']];
summary.getRange('A42').format.font={italic:true,color:'#58695E'};
const widths=[160,122,122,125,150,145,145,150,150,155,175];
for(let c=0;c<widths.length;c++) summary.getRangeByIndexes(0,c,42,1).format.columnWidthPx=widths[c];
summary.getRange('A1:K42').format.verticalAlignment='center';

const headers=['Image','Cell ID','Row','Column','Cell status','Total cell (px)','Old grooves (px)','Eligible AM (px)','Loss (px)','Retained (px)','Loss (%)','Retained (%)','Stricter loss (px)','Stricter loss (%)','Bright-change (px)','Bright-change (%)','Dark-pit (px)','Dark-pit (%)'];
cells.getRange('A1:R1').values=[headers];
cells.getRange('A1:R1').format={fill:'#284F3D',font:{bold:true,color:'#FFFFFF'},wrapText:true,horizontalAlignment:'center',verticalAlignment:'center',rowHeight:34};
cells.getRange('A1:R1').format.borders={insideVertical:{style:'thin',color:'#FFFFFF'}};
const sourceRows=results.flatMap(r=>r.per_cell.map(c=>[r.image,c.cell,c.row,c.column,null,c.total_cell_px,c.groove_excluded_px,c.eligible_am_px,c.loss_px,null,null,null,c.strict_loss_px,null,c.bright_loss_px,null,c.dark_pit_loss_px,null]));
cells.getRange('A2:R325').values=sourceRows;
for(let j=0;j<sourceRows.length;j++) {
 const r=j+2;
 cells.getRange(`E${r}`).formulas=[[`=IF(H${r}=0,"Excluded",IF(I${r}=0,"Intact","Damaged"))`]];
 cells.getRange(`J${r}:L${r}`).formulas=[[`=H${r}-I${r}`,`=IF(H${r}=0,NA(),I${r}/H${r})`,`=IF(H${r}=0,NA(),J${r}/H${r})`]];
 cells.getRange(`N${r}`).formulas=[[`=IF(H${r}=0,NA(),M${r}/H${r})`]];
 cells.getRange(`P${r}`).formulas=[[`=IF(H${r}=0,NA(),O${r}/H${r})`]];
 cells.getRange(`R${r}`).formulas=[[`=IF(H${r}=0,NA(),Q${r}/H${r})`]];
}
cells.getRange('A2:J325').setNumberFormat('#,##0');cells.getRange('M2:M325').setNumberFormat('#,##0');cells.getRange('O2:O325').setNumberFormat('#,##0');cells.getRange('Q2:Q325').setNumberFormat('#,##0');
for(const col of ['K','L','N','P','R']) cells.getRange(`${col}2:${col}325`).setNumberFormat('0.00%');
cells.getRange('E2:E325').conditionalFormats.add('containsText',{text:'Damaged',format:{fill:'#FCE3C5'}});
cells.getRange('E2:E325').conditionalFormats.add('containsText',{text:'Intact',format:{fill:'#FFF4BF'}});
cells.getRange('E2:E325').conditionalFormats.add('containsText',{text:'Excluded',format:{fill:'#FAD0CB'}});
cells.getRange('K2:K325').conditionalFormats.add('colorScale',{colors:['#EDF4F9','#C7E5F5','#70BBE4'],thresholds:['min',{type:'percentile',value:50},'max']});
cells.getRange('A2:R325').format.rowHeight=20;
const cellWidths=[65,75,65,70,115,125,130,130,110,125,110,120,140,140,155,155,130,130];
for(let c=0;c<cellWidths.length;c++) cells.getRangeByIndexes(0,c,325,1).format.columnWidthPx=cellWidths[c];
cells.freezePanes.freezeRows(1);cells.freezePanes.freezeColumns(2);
const table=cells.tables.add('A1:R325',true,'S16CellResults');

wb.recalculate();
console.log((await wb.inspect({kind:'table',range:'Summary!A5:K11',include:'values,formulas',tableMaxRows:8,tableMaxCols:11,maxChars:5000})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},summary:'final formula error scan',maxChars:2000})).ndjson);
const actual=summary.getRange('H6:K9').values;
for(let i=0;i<4;i++) {
 const expected=[results[i].loss_fraction,results[i].intact_fraction,results[i].strict_loss_fraction,results[i].bright_loss_fraction];
 for(let j=0;j<4;j++) if(Math.abs(actual[i][j]-expected[j])>1e-10) throw new Error(`Summary mismatch ${i},${j}: ${actual[i][j]} vs ${expected[j]}`);
}
await fs.mkdir(outputDir,{recursive:true});
for (const [sheetName,range,file] of [['Summary','A1:K26','workbook_summary_preview.png'],['Cells','A1:R11','workbook_cells_preview.png']]) {
 const blob=await wb.render({sheetName,range,scale:1.4,format:'png'});
 await fs.writeFile(`${root}/analysis/${file}`,new Uint8Array(await blob.arrayBuffer()));
}
const output=await SpreadsheetFile.exportXlsx(wb);await output.save(`${outputDir}/S16_Step2_Adhesion_Results.xlsx`);
console.log('Exported S16_Step2_Adhesion_Results.xlsx; all four summary rows match the pixel-mask counts.');
