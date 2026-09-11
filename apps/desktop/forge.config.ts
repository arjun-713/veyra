import type {ForgeConfig} from '@electron-forge/shared-types';
import {VitePlugin} from '@electron-forge/plugin-vite';
import {MakerSquirrel} from '@electron-forge/maker-squirrel';
import {MakerZIP} from '@electron-forge/maker-zip';
import {MakerDeb} from '@electron-forge/maker-deb';
import {MakerDMG} from '@electron-forge/maker-dmg';
const macSigning=process.env.APPLE_SIGN_IDENTITY?{osxSign:{identity:process.env.APPLE_SIGN_IDENTITY},...(process.env.APPLE_ID&&process.env.APPLE_APP_SPECIFIC_PASSWORD&&process.env.APPLE_TEAM_ID?{osxNotarize:{appleId:process.env.APPLE_ID,appleIdPassword:process.env.APPLE_APP_SPECIFIC_PASSWORD,teamId:process.env.APPLE_TEAM_ID}}:{})}:{};
const windowsSigning=process.env.WINDOWS_CERTIFICATE_FILE&&process.env.WINDOWS_CERTIFICATE_PASSWORD?{certificateFile:process.env.WINDOWS_CERTIFICATE_FILE,certificatePassword:process.env.WINDOWS_CERTIFICATE_PASSWORD}:{};
const config:ForgeConfig={
 packagerConfig:{asar:true,executableName:'veyra',...macSigning,...(process.env.VEYRA_BACKEND_BUNDLE?{extraResource:[process.env.VEYRA_BACKEND_BUNDLE]}:{})},
 makers:[new MakerSquirrel({name:'veyra',...windowsSigning}),new MakerZIP({},['darwin','linux']),new MakerDeb({options:{name:'veyra',productName:'Veyra',bin:'veyra',categories:['Science'],maintainer:'Veyra contributors',homepage:'https://github.com/arjun-713/veyra'}}),new MakerDMG({})],
 plugins:[new VitePlugin({build:[{entry:'src/main.ts',config:'vite.main.config.ts'},{entry:'src/preload.ts',config:'vite.preload.config.ts'}],renderer:[{name:'main_window',config:'vite.renderer.config.ts'}]})]
};export default config;
