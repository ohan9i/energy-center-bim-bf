import {findRoute} from './navigation';
self.onmessage=event=>{try {self.postMessage({result:findRoute(event.data.model,event.data.start,event.data.end,event.data.profile)});}catch(error){self.postMessage({error:error instanceof Error?error.message:String(error)});}};
