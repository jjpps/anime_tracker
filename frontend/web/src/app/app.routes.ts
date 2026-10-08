import { Routes } from '@angular/router';
import { AnimePage } from './anime';
import { LargadosPage } from './largados';
import { NovidadesPage } from './novidades';

export const routes: Routes = [
  { path: '', component: NovidadesPage, title: 'Novidades · anime tracker' },
  { path: 'largados', component: LargadosPage, title: 'Parei de acompanhar · anime tracker' },
  { path: 'anime/:id', component: AnimePage, title: 'Anime · anime tracker' },
  { path: '**', redirectTo: '' },
];
