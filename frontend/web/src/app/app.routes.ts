import { Routes } from '@angular/router';
import { LargadosPage } from './largados';
import { NovidadesPage } from './novidades';

export const routes: Routes = [
  { path: '', component: NovidadesPage, title: 'Novidades · anime tracker' },
  { path: 'largados', component: LargadosPage, title: 'Parei de acompanhar · anime tracker' },
  { path: '**', redirectTo: '' },
];
