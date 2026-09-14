import fs from 'node:fs';
import {DEFAULTS,FIELDS,SOURCES} from '../solar-ev-studio/studio-core.mjs';
const root=new URL('custom_components/solar_ev_studio/',import.meta.url);
fs.mkdirSync(new URL('frontend/',root),{recursive:true});fs.mkdirSync(new URL('translations/',root),{recursive:true});
fs.writeFileSync(new URL('settings.json',root),JSON.stringify({defaults:DEFAULTS,fields:FIELDS,sources:SOURCES},null,2));
fs.writeFileSync(new URL('manifest.json',root),JSON.stringify({domain:'solar_ev_studio',name:'Solar EV Studio',version:'1.0.0',config_flow:true,documentation:'https://developers.home-assistant.io/docs/creating_integration_manifest/',integration_type:'service',iot_class:'local_push',dependencies:['frontend','http','panel_custom','websocket_api'],requirements:[],codeowners:[]},null,2));
const strings={title:'Solar EV Studio',config:{step:{user:{title:'Solar EV Studio',description:'Create a solar EV charging controller with a full Studio settings panel. Starts paused. Open Solar EV Studio in the sidebar to select entities and edit all settings. Enabling solar mode hands control over from the earlier Solar EV automations.'}},abort:{already_configured:'Solar EV Studio is already configured.'}},options:{step:{init:{title:'Solar EV Studio settings',description:'Open [Solar EV Studio](/solar-ev-studio) in the sidebar to edit every setting and entity mapping. Settings are saved directly in this integration. Saving pauses charging.'}}}};
fs.writeFileSync(new URL('strings.json',root),JSON.stringify(strings,null,2));fs.writeFileSync(new URL('translations/en.json',root),JSON.stringify(strings,null,2));
let core=fs.readFileSync(new URL('../solar-ev-studio/studio-core.mjs',import.meta.url),'utf8').split('export function compile')[0].replaceAll('export ','');
let ui=fs.readFileSync(new URL('../solar-ev-studio/studio-ui.js',import.meta.url),'utf8').split("if(!customElements.get('solar-ev-studio'))")[0].replace('class SolarEVStudio','class IntegrationEditor');
// The rendered form is shared; all control and persistence methods are overridden below.
ui=ui.slice(0,ui.indexOf(' async save(){'))+'}\n';
ui=ui.replace('Settings are applied to Home Assistant and continue working with this screen closed.','Settings are saved in the Solar EV Studio integration and continue working with this screen closed.');
const panel=fs.readFileSync(new URL('panel.js',import.meta.url),'utf8');
fs.writeFileSync(new URL('frontend/studio.js',root),core+'\n'+ui+'\n'+panel);
